#!/usr/bin/python
#
# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wrapper for tests that are run on builders."""

import distutils.version
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
  # Archive directory the buildbot stores images.
  LOCAL_ARCHIVE = '/var/www/archive'
  # The image we want to test.
  IMAGE_TO_EXTRACT = 'chromiumos_test_image.bin'
  # Archive directory in the src tree to keep latest archived image after
  # we've unzipped them.
  SRC_ARCHIVE_DIR = 'latest_image'

  def __init__(self, build_config):
    """Initializes a extractor for the build_config."""
    self.archive = os.path.join(self.LOCAL_ARCHIVE, build_config)

  def GetLatestImage(self, target_version):
    """Gets the last image archived for the board.

    Args:
      target_version:  The version that is being tested.  The archive
        directory may be being populated with the results of this version
        while we're running so we shouldn't use it as the last image archived.
    """
    if os.path.exists(self.archive):
      my_re = re.compile(r'R\d+-(\d+)\.(\d+)\.(\d+)-.*')
      filelist = []
      target_lv = distutils.version.LooseVersion(target_version)
      for filename in os.listdir(self.archive):
        lv = distutils.version.LooseVersion(filename)
        if my_re.match(filename):
          if lv < target_lv:
            filelist.append(lv)
          elif not filename.startswith(target_version):
            logging.error('Version in archive dir is too new: %s' % filename)
      if filelist:
        return os.path.join(self.archive, str(max(filelist)))

    return None

  def UnzipImage(self, image_dir):
    """Unzips the image.zip from the image_dir and returns the image."""
    # We include the dirname of the image here so that we don't have to
    # re-unzip the same one each time.
    local_path = os.path.join(self.SRC_ARCHIVE_DIR,
                              os.path.basename(image_dir))
    image_to_return = os.path.abspath(os.path.join(local_path,
                                                   self.IMAGE_TO_EXTRACT))
    # We only unzip it if we don't have it.
    if not os.path.exists(image_to_return):
      # We don't want to keep test self.SRC_ARCHIVE_DIRs around.
      if os.path.exists(self.SRC_ARCHIVE_DIR):
        logging.info('Removing old archive from %s', self.SRC_ARCHIVE_DIR)
        shutil.rmtree(self.SRC_ARCHIVE_DIR)

      logging.info('Creating directory %s to store image for testing.',
                   local_path)
      os.makedirs(local_path)
      zip_path = os.path.join(image_dir, 'image.zip')
      logging.info('Unzipping image from %s', zip_path)
      chromite_build_lib.RunCommand(['unzip', '-d', local_path, zip_path],
                                    print_cmd=False)

    return image_to_return


class TestException(Exception):
  """Thrown by RunAUTestHarness if there's a test failure."""
  pass


class CTest(object):
  """Main class with methods to generate payloads and test them.

  Variables:
    base: Base image to test from.
    board: the board for the latest image.
    build_config: Build configuration we are testing.
    crosutils_root: Location of crosutils.
    jobs: Numbers of threads to run in parallel.
    no_graphics: boolean: If True, disable graphics during vm test.
    nplus1_archive_dir: Archive directory to store nplus1 payloads.
    private_key: Signs payloads with this key.
    public_key: Loads key to verify signed payloads.
    remote: ip address for real test harness run.
    sign_payloads: Build some payloads with signed keys.
    target: Target image to test.
    test_results_root: Root directory to store au_test_harness results.
    type: which test harness to run.  Possible values: real, vm.
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

    self.jobs = options.jobs
    self.nplus1_archive_dir = options.nplus1_archive_dir

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
      target_version = os.path.realpath(self.target).rsplit('/', 2)[-2]
      extractor = ImageExtractor(self.build_config)
      latest_image_dir = extractor.GetLatestImage(target_version)
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
    cmd.append('--jobs=%d' % self.jobs)
    if full:
      cmd.append('--full_suite')
      cmd.append('--nplus1')
      if self.nplus1_archive_dir:
        cmd.append('--nplus1_archive_dir=%s' % self.nplus1_archive_dir)

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

  def RunAUTestHarness(self, full, only_verify):
    """Runs the auto update test harness.

    The auto update test harness encapsulates testing the auto-update mechanism
    for the latest image against the latest official image from the channel.
    This also tests images with suite_Smoke (built-in as part of its
    verification process).

    Args:
      full: Run full test suite.
      only_verify: Only verify the target image.
    Raises:
      TestException: If the cros_au_test_harness command returns an error code.
    """
    cmd = ['bin/cros_au_test_harness',
           '--base_image=%s' % self.base,
           '--target_image=%s' % self.target,
           '--board=%s' % self.board,
           '--type=%s' % self.type,
           '--remote=%s' % self.remote,
           '--verbose',
           '--jobs=%d' % self.jobs,
          ]

    if not full:
      if only_verify:
        cmd.append('--test_prefix=SimpleTestVerify')
      else:
        cmd.append('--test_prefix=SimpleTest')

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
  parser.add_option('--jobs', default=test_helper.CalculateDefaultJobs(),
                    type=int,
                    help='Number of threads to run in parallel.')
  parser.add_option('--no_graphics', action='store_true', default=False,
                    help='Disable graphics for the vm test.')
  parser.add_option('--only_verify', action='store_true', default=False,
                    help='Only run basic verification suite.')
  parser.add_option('--quick', default=True, action='store_false',
                    dest='full_suite',
                    help='Run the quick version of ctest.')
  parser.add_option('--nplus1_archive_dir', default=None,
                    help='If set, directory to archive nplus1 payloads.')
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

  # force absolute path for these options, since a chdir occurs deeper in the
  # codebase.
  for x in ('nplus1_archive_dir', 'target_image', 'test_results_root'):
    val = getattr(options, x)
    if val is not None:
      setattr(options, x, os.path.abspath(val))

  ctest = CTest(options)
  if ctest.sign_payloads: ctest.GeneratePublicKey()
  ctest.FindTargetAndBaseImages()
  if not options.only_verify:
    ctest.GenerateUpdatePayloads(options.full_suite)
  try:
    ctest.RunAUTestHarness(options.full_suite, options.only_verify)
  except TestException as e:
    if options.verbose:
      chromite_build_lib.Die(str(e))

    sys.exit(1)


if __name__ == '__main__':
  main()
