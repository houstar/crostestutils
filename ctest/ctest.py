#!/usr/bin/python
#
# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wrapper for tests that are run on builders."""

import logging
import optparse
import os
import re
import shutil
import sys

import constants
sys.path.append(constants.CROSUTILS_LIB_DIR)
sys.path.append(constants.SOURCE_ROOT)
sys.path.append(constants.CROS_PLATFORM_ROOT)

import chromite.lib.cros_build_lib as chromite_build_lib
from crostestutils.lib import test_helper


class ImageExtractor(object):
  """Class used to get the latest image for the board."""
  LOCAL_ARCHIVE = '/var/www/archive'
  IMAGE_TO_EXTRACT = 'chromiumos_test_image.bin'

  def __init__(self, build_config):
    """Initializes a extractor for the build_config."""
    self.archive = os.path.join(self.LOCAL_ARCHIVE, build_config)

  def GetLatestImage(self):
    """Gets the latest archive image for the board."""
    my_re = re.compile(r'(\d+)\.(\d+)\.(\d+).*')

    def VersionCompare(version):
      return map(int, my_re.match(version).groups())

    if os.path.exists(self.archive):
      filelist = os.listdir(self.archive)
      filelist = [f for f in filelist if not os.path.isdir(f)]
      newest = max(filelist, key=VersionCompare)
      return os.path.join(self.archive, newest)

    return None

  def UnzipImage(self, image_dir):
    """Unzips the image.zip from the image_dir and returns the image."""
    local_path = 'latest_image'
    if os.path.isdir(local_path):
      logging.info('Removing cached image from %s', local_path)
      shutil.rmtree(local_path)

    os.makedirs(local_path)
    zip_path = os.path.join(image_dir, 'image.zip')
    logging.info('Unzipping image from %s', zip_path)
    chromite_build_lib.RunCommand(['unzip', '-d', local_path, zip_path],
                                  print_cmd=False)

    return os.path.abspath(os.path.join(local_path, self.IMAGE_TO_EXTRACT))


class TestException(Exception):
  """ Thrown by RunAUTestHarness if there's a test failure. """
  pass


class CTest(object):
  """Main class with methods to generate payloads and test them.

  Variables:
    base: Base image to test from.
    board: the board for the latest image.
    build_config: Build configuration we are testing.
    crosutils_root:  Location of crosutils.
    no_graphics: boolean - If True, disable graphics during vm test.
    remote: ip address for real test harness run.
    type: which test harness to run.  Possible values: real, vm.
    private_key:  Signs payloads with this key.
    public_key:  Loads key to verify signed payloads.
    sign_payloads: Build some payloads with signed keys.
    target: Target image to test.
    test_results_root: Root directory to store au_test_harness results.
  """
  def __init__(self, options):
    """Initializes the test object.

    Args:
      options:  Parsed options for module.
    """
    self.base = None
    self.board = options.board
    self.build_config = options.build_config
    self.crosutils_root = os.path.join(constants.SOURCE_ROOT, 'src', 'scripts')
    self.no_graphics = options.no_graphics
    self.remote = options.remote
    # TODO(sosa):  Remove once signed payload bug is resolved.
    #self.sign_payloads = not options.cache
    self.sign_payloads = False
    self.target = options.target_image
    self.test_results_root = options.test_results_root
    self.type = options.type

    self.public_key = None
    if self.sign_payloads:
      self.private_key = os.path.realpath(
          os.path.join(self.crosutils_root, '..', 'platform', 'update_engine',
                       'unittest_key.pem'))
    else:
      self.private_key = None

  def GeneratePublicKey(self):
    """Returns the path to a generated public key from the UE private key."""
    # Just output to local directory.
    public_key_path = 'public_key.pem'
    logging.info('Generating public key from private key.')
    chromite_build_lib.RunCommand(
        ['openssl', 'rsa', '-in', self.private_key, '-pubout',
         '-out', public_key_path], print_cmd=False)
    self.public_key = public_key_path

  def FindTargetAndBaseImages(self):
    """Initializes the target and base images for CTest."""
    if not self.target:
      # Grab the latest image we've built.
      return_object = chromite_build_lib.RunCommand(
          ['./get_latest_image.sh', '--board=%s' % self.board],
          cwd=self.crosutils_root, redirect_stdout=True, print_cmd=False)

      latest_image_dir = return_object.output.strip()
      self.target = os.path.join(latest_image_dir,
                                 ImageExtractor.IMAGE_TO_EXTRACT)

    # Grab the latest official build for this board to use as the base image.
    if self.build_config:
      extractor = ImageExtractor(self.build_config)
      latest_image_dir = extractor.GetLatestImage()
      if latest_image_dir:
        self.base = extractor.UnzipImage(latest_image_dir)

    if not self.base:
      logging.info('Could not find a latest image to use. '
                   'Using target instead.')
      self.base = self.target

  def GenerateUpdatePayloads(self, full):
    """Generates payloads for the test harness.

    Args:
      full: Build payloads for full test suite.
    """
    generator = ('../platform/crostestutils/'
                 'generate_test_payloads/cros_generate_test_payloads.py')

    cmd = [generator]
    cmd.append('--target=%s' % self.target)
    cmd.append('--base=%s' % self.base)
    cmd.append('--board=%s' % self.board)
    if full:
      cmd.append('--full_suite')
      cmd.append('--nplus1')
      if self.sign_payloads:
        cmd.append('--public_key=%s' % self.public_key)
        cmd.append('--private_key=%s' % self.private_key)

    if self.type != 'vm': cmd.append('--novm')
    try:
      chromite_build_lib.RunCommand(cmd, cwd=self.crosutils_root)
    except chromite_build_lib.RunCommandError:
      logging.error('We failed to generate all the update payloads required '
                    'for testing. Please see the logs for more info. We print '
                    'out the log from a failing call to '
                    'cros_generate_update_payload for error handling.')
      sys.exit(1)

  def RunAUTestHarness(self, full):
    """Runs the auto update test harness.

    The auto update test harness encapsulates testing the auto-update mechanism
    for the latest image against the latest official image from the channel.
    This also tests images with suite_Smoke (built-in as part of its
    verification process).

    Args:
      full: Run full test suite.
    """
    cmd = ['bin/cros_au_test_harness',
           '--base_image=%s' % self.base,
           '--target_image=%s' % self.target,
           '--board=%s' % self.board,
           '--type=%s' % self.type,
           '--remote=%s' % self.remote,
           '--verbose',
          ]

    if not full: cmd.append('--test_prefix=SimpleTest')

    if self.test_results_root: cmd.append('--test_results_root=%s' %
                                          self.test_results_root)
    if self.no_graphics: cmd.append('--no_graphics')

    # Using keys is only compatible with clean.
    if full and self.sign_payloads:
      cmd.append('--private_key=%s' % self.private_key)

    res = chromite_build_lib.RunCommand(cmd, cwd=self.crosutils_root,
                                        error_ok=True, exit_code=True)
    if res.returncode != 0:
      raise TestException('%s exited with code %d: %s' % (' '.join(res.cmd),
                                                          res.returncode,
                                                          res.error))


def main():
  test_helper.SetupCommonLoggingFormat()
  parser = optparse.OptionParser()
  parser.add_option('-b', '--board',
                    help='board for the image to compare against.')
  parser.add_option('--build_config',
                    help='Name for the build configuration we are archiving.')
  parser.add_option('--cache', default=False, action='store_true',
                    help='Cache payloads')
  parser.add_option('--no_graphics', action='store_true', default=False,
                    help='Disable graphics for the vm test.')
  parser.add_option('--quick', default=True, action='store_false',
                    dest='full_suite',
                    help='Run the quick version of ctest.')
  parser.add_option('--remote', default='0.0.0.0',
                    help='For real tests, ip address of the target machine.')
  parser.add_option('--target_image', default=None,
                    help='Target image to test.')
  parser.add_option('--test_results_root', default=None,
                    help='Root directory to store test results.  Should '
                    'be defined relative to chroot root.')
  parser.add_option('--type', default='vm',
                    help='type of test to run: [vm, real]. Default: vm.')
  parser.add_option('--verbose', default=False, action='store_true',
                    help='Print out added debugging information')

  # Set the usage to include flags.
  parser.set_usage(parser.format_help())
  (options, args) = parser.parse_args()

  if args: parser.error('Extra args found %s.' % args)
  if not options.board: parser.error('Need board for image to compare against.')

  ctest = CTest(options)
  if ctest.sign_payloads: ctest.GeneratePublicKey()
  ctest.FindTargetAndBaseImages()
  ctest.GenerateUpdatePayloads(options.full_suite)
  try:
    ctest.RunAUTestHarness(options.full_suite)
  except TestException as e:
    if options.verbose:
      cros_lib.Die(str(e))

    sys.exit(1)


if __name__ == '__main__':
  main()
