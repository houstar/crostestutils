#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wrapper for tests that are run on builders."""

import logging
import optparse
import os
import sys

import constants
sys.path.append(constants.CROSUTILS_LIB_DIR)
sys.path.append(constants.SOURCE_ROOT)
sys.path.append(constants.CROS_PLATFORM_ROOT)

from chromite.lib import cros_build_lib
from crostestutils.lib import image_extractor
from crostestutils.lib import test_helper


class TestException(Exception):
  """Thrown by RunAUTestHarness if there's a test failure."""


class CTest(object):
  """Main class with methods to generate payloads and test them.

  Variables:
    base: Base image to test from.
    board: the board for the latest image.
    archive_dir: Location where images for past versions are archived.
    crosutils_root: Location of crosutils.
    jobs: Numbers of threads to run in parallel.
    no_graphics: boolean: If True, disable graphics during vm test.
    nplus1_archive_dir: Archive directory to store nplus1 payloads.
    payload_signing_key: Signs payloads with this key.
    public_key: Loads key to verify signed payloads.
    remote: ip address for real test harness run.
    sign_payloads: Build some payloads with signed keys.
    target: Target image to test.
    test_results_root: Root directory to store au_test_harness results.
    type: which test harness to run.  Possible values: real, vm, gce.
    whitelist_chrome_crashes: Whether to treat Chrome crashes as non-fatal.
  """

  def __init__(self, options):
    """Initializes the test object.

    Args:
      options:  Parsed options for module.
    """
    self.base = None
    self.board = options.board
    self.archive_dir = options.archive_dir
    self.crosutils_root = os.path.join(constants.SOURCE_ROOT, 'src', 'scripts')
    self.no_graphics = options.no_graphics
    self.remote = options.remote
    # TODO(sosa):  Remove once signed payload bug is resolved.
    #self.sign_payloads = not options.cache
    self.sign_payloads = False
    self.target = options.target_image
    self.test_results_root = options.test_results_root
    self.type = options.type
    self.whitelist_chrome_crashes = options.whitelist_chrome_crashes

    self.public_key = None
    if self.sign_payloads:
      self.payload_signing_key = os.path.realpath(
          os.path.join(self.crosutils_root, '..', 'platform', 'update_engine',
                       'unittest_key.pem'))
    else:
      self.payload_signing_key = None

    self.jobs = options.jobs
    self.nplus1_archive_dir = options.nplus1_archive_dir

    # An optional ssh private key used for testing.
    self.ssh_private_key = options.ssh_private_key

  def GeneratePublicKey(self):
    """Returns the path to a generated public key from the UE private key."""
    # Just output to local directory.
    public_key_path = 'public_key.pem'
    logging.info('Generating public key from private key.')
    cros_build_lib.RunCommand(
        ['openssl', 'rsa', '-in', self.payload_signing_key, '-pubout',
         '-out', public_key_path], print_cmd=False)
    self.public_key = public_key_path

  def FindTargetAndBaseImages(self):
    """Initializes the target and base images for CTest."""
    if not self.target:
      # Grab the latest image we've built.
      return_object = cros_build_lib.RunCommand(
          ['./get_latest_image.sh', '--board=%s' % self.board],
          cwd=self.crosutils_root, redirect_stdout=True, print_cmd=False)

      latest_image_dir = return_object.output.strip()
      self.target = os.path.join(
          latest_image_dir, image_extractor.ImageExtractor.IMAGE_TO_EXTRACT)


    # Grab the latest official build for this board to use as the base image.
    if self.archive_dir:
      target_version = os.path.realpath(self.target).rsplit('/', 2)[-2]
      extractor = image_extractor.ImageExtractor(self.archive_dir)
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
    if self.nplus1_archive_dir:
      cmd.append('--nplus1')
      cmd.append('--nplus1_archive_dir=%s' % self.nplus1_archive_dir)

    if full:
      cmd.append('--full_suite')
      # This only is compatible with payload signing.
      if self.sign_payloads:
        cmd.append('--public_key=%s' % self.public_key)
        cmd.append('--private_key=%s' % self.payload_signing_key)
    else:
      cmd.append('--basic_suite')

    if self.type != 'vm': cmd.append('--novm')
    try:
      cros_build_lib.RunCommand(cmd, cwd=self.crosutils_root)
    except cros_build_lib.RunCommandError:
      logging.error('We failed to generate all the update payloads required '
                    'for testing. Please see the logs for more info. We print '
                    'out the log from a failing call to '
                    'cros_generate_update_payload for error handling.')
      sys.exit(1)

  def RunAUTestHarness(self, only_verify, quick_update, suite):
    """Runs the auto update test harness.

    The auto update test harness encapsulates testing the auto-update mechanism
    for the latest image against the latest official image from the channel.
    This also tests images with suite:smoke (built-in as part of its
    verification process).

    Args:
      only_verify: Only verify the target image.
      quick_update: Do a quick update test.
    Raises:
      TestException: If the cros_au_test_harness command returns an error code.
    """
    path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    cmd = [os.path.join(path, 'au_test_harness', 'cros_au_test_harness.py'),
           '--base_image=%s' % self.base,
           '--target_image=%s' % self.target,
           '--board=%s' % self.board,
           '--type=%s' % self.type,
           '--remote=%s' % self.remote,
           '--verbose',
           '--jobs=%d' % self.jobs,
          ]

    if self.ssh_private_key is not None:
      cmd.append('--ssh_private_key=%s' % self.ssh_private_key)

    if suite:
      cmd.append('--verify_suite_name=%s' % suite)

    if only_verify:
      cmd.append('--test_prefix=SimpleTestVerify')
    elif quick_update:
      cmd.append('--test_prefix=SimpleTestUpdateAndVerify')

    if self.test_results_root: cmd.append('--test_results_root=%s' %
                                          self.test_results_root)
    if self.no_graphics: cmd.append('--no_graphics')
    if self.whitelist_chrome_crashes: cmd.append('--whitelist_chrome_crashes')

    # We did not generate signed payloads if this is a |quick_update| test.
    if not quick_update and self.sign_payloads:
      cmd.append('--payload_signing_key=%s' % self.payload_signing_key)

    res = cros_build_lib.RunCommand(cmd, cwd=self.crosutils_root,
                                    error_code_ok=True)
    if res.returncode != 0:
      raise TestException('%s exited with code %d: %s' % (' '.join(res.cmd),
                                                          res.returncode,
                                                          res.error))


def main():
  test_helper.SetupCommonLoggingFormat()
  parser = optparse.OptionParser()
  parser.add_option('-b', '--board',
                    help='board for the image to compare against.')
  parser.add_option('--archive_dir',
                    help='Directory containing previously archived images.')
  parser.add_option('--cache', default=False, action='store_true',
                    help='Cache payloads')
  parser.add_option('--jobs', default=test_helper.CalculateDefaultJobs(),
                    type=int,
                    help='Number of threads to run in parallel.')
  parser.add_option('--no_graphics', action='store_true', default=False,
                    help='Disable graphics for the vm test.')
  parser.add_option('--only_verify', action='store_true', default=False,
                    help='Only run basic verification suite.')
  parser.add_option('--quick_update', action='store_true',
                    help='Run a quick update test. This will run a subset of '
                         'test suite after running autoupdate from target '
                         'image to itself.')
  parser.add_option('--nplus1_archive_dir', default=None,
                    help='If set, directory to archive nplus1 payloads.')
  parser.add_option('--remote', default='0.0.0.0',
                    help='For real tests, ip address of the target machine.')
  parser.add_option('--target_image', default=None,
                    help='Target image to test.')
  parser.add_option('--suite', default=None, help='Test suite to run.')
  parser.add_option('--test_results_root', default=None,
                    help='Root directory to store test results.  Should '
                    'be defined relative to chroot root.')
  parser.add_option('--type', default='vm',
                    help='type of test to run: [vm, real, gce]. Default: vm.')
  parser.add_option('--verbose', default=False, action='store_true',
                    help='Print out added debugging information')
  parser.add_option('--whitelist_chrome_crashes', default=False,
                    dest='whitelist_chrome_crashes', action='store_true',
                    help='Treat Chrome crashes as non-fatal.')
  parser.add_option('--ssh_private_key', default=None,
                    help='Path to the private key to use to ssh into the image '
                    'as the root user')

  # Set the usage to include flags.
  def _ParserError(msg):
    print >> sys.stderr, parser.format_help()
    print >> sys.stderr, 'Error: %s' % msg
    sys.exit(2)
  parser.error = _ParserError
  (options, args) = parser.parse_args()

  if args: parser.error('Extra args found %s.' % args)
  if not options.board: parser.error('Need board for image to compare against.')
  if options.only_verify and options.quick_update: parser.error(
      'Only one of --only_verify or --quick_update should be specified.')

  # force absolute path for these options, since a chdir occurs deeper in the
  # codebase.
  for x in ('nplus1_archive_dir', 'target_image', 'test_results_root'):
    if x == 'target_image' and options.type == 'gce':
      # In this case |target_image| is a Google Storage path.
      continue
    val = getattr(options, x)
    if val is not None:
      setattr(options, x, os.path.abspath(val))

  ctest = CTest(options)
  if ctest.sign_payloads: ctest.GeneratePublicKey()
  ctest.FindTargetAndBaseImages()
  if not options.only_verify:
    ctest.GenerateUpdatePayloads(not options.quick_update)
  try:
    ctest.RunAUTestHarness(options.only_verify, options.quick_update,
                           options.suite)
  except TestException as e:
    if options.verbose:
      cros_build_lib.Die(str(e))

    sys.exit(1)


if __name__ == '__main__':
  main()
