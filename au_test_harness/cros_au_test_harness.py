#!/usr/bin/python

# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module runs a suite of Auto Update tests.

  The tests can be run on either a virtual machine or actual device depending
  on parameters given.  Specific tests can be run by invoking --test_prefix.
  Verbose is useful for many of the tests if you want to see individual commands
  being run during the update process.
"""

import optparse
import os
import pickle
import sys
import tempfile
import traceback
import StringIO
import unittest

# TODO(sosa): Migrate to chromite cros_build_lib.
import constants
sys.path.append(constants.CROSUTILS_LIB_DIR)
sys.path.append(constants.CROS_PLATFORM_ROOT)
import cros_build_lib as cros_lib

from crostestutils.au_test_harness import au_test
from crostestutils.au_test_harness import au_worker
from crostestutils.lib import dev_server_wrapper
from crostestutils.lib import parallel_test_job
from crostestutils.lib import test_helper

# File location for update cache in given folder.
CACHE_FILE = 'update.cache'


class _LessBacktracingTestResult(unittest._TextTestResult):
  """TestResult class that suppresses stacks for AssertionError."""
  def addFailure(self, test, err):
    """Overrides unittest.TestCase.addFailure to suppress stack traces."""
    exc_type, exc_value = err[:2]
    if exc_type is AssertionError:  # There's already plenty of debug output.
      self.failures.append((test, ''))
    else:
      super(AUTest, self).addFailure(test, err)


class _LessBacktracingTestRunner(unittest.TextTestRunner):
  """TestRunner class that suppresses stacks for AssertionError."""
  def _makeResult(self):
    return _LessBacktracingTestResult(self.stream,
                                      self.descriptions,
                                      self.verbosity)


def _ReadUpdateCache(target_image):
  """Reads update cache from generate_test_payloads call."""
  path_to_dump = os.path.dirname(target_image)
  cache_file = os.path.join(path_to_dump, CACHE_FILE)

  if os.path.exists(cache_file):
    cros_lib.Info('Loading update cache from ' + cache_file)
    with open(cache_file) as file_handle:
      return pickle.load(file_handle)

  return None


def _PrepareTestSuite(options):
  """Returns a prepared test suite given by the options and test class."""
  au_test.AUTest.ProcessOptions(options)
  test_loader = unittest.TestLoader()
  test_loader.testMethodPrefix = options.test_prefix
  return test_loader.loadTestsFromTestCase(au_test.AUTest)


def _RunTestsInParallel(options):
  """Runs the tests given by the options in parallel."""
  test_suite = _PrepareTestSuite(options)
  threads = []
  args = []
  for test in test_suite:
    test_name = test.id()
    test_case = unittest.TestLoader().loadTestsFromName(test_name)
    threads.append(_LessBacktracingTestRunner().run)
    args.append(test_case)

  cros_lib.Info('Running tests in test suite in parallel.')
  results = parallel_test_job.RunParallelJobs(options.jobs, threads, args)
  for test_result in results:
    if test_result is None or not test_result.wasSuccessful():
      # TODO(sosa): Fix max recursion depth warnings. http://crosbug.com/14274
      cros_lib.Die(
          'Test harness was not successful. See logs for details. '
          'Note: Max recursion depth warnings are normal and occur regardless '
          'of success or failure. Scroll up past the warnings to see the '
          'actual failures.')


def CheckOptions(parser, options, leftover_args):
  """Assert given options are valid.

  Args:
    parser: Parser used to parse options.
    options:  Parsed options.
    leftover_args:  Args left after parsing.
  """
  if leftover_args: parser.error('Found unsupported flags ' + leftover_args)
  if not options.type in ['real', 'vm']:
    parser.error('Failed to specify valid test type.')

  if not options.target_image or not os.path.isfile(options.target_image):
    parser.error('Testing requires a valid target image.')

  if not options.base_image:
    cros_lib.Info('Base image not specified.  Using target as base image.')
    options.base_image = options.target_image

  if not os.path.isfile(options.base_image):
    parser.error('Testing requires a valid base image.')

  if options.private_key and not os.path.isfile(options.private_key):
    parser.error('Testing requires a valid path to the private key.')

  if options.test_results_root:
    if not 'chroot/tmp' in options.test_results_root:
      parser.error('Must specify a test results root inside tmp in a chroot.')

    if not os.path.exists(options.test_results_root):
      os.makedirs(options.test_results_root)

  else:
    options.test_results_root = tempfile.mkdtemp(
        prefix='au_test_harness', dir=cros_lib.PrependChrootPath('/tmp'))


def main():
  parser = optparse.OptionParser()
  parser.add_option('-b', '--base_image',
                    help='path to the base image.')
  parser.add_option('-r', '--board',
                    help='board for the images.')
  parser.add_option('--no_delta', action='store_false', default=True,
                    dest='delta',
                    help='Disable using delta updates.')
  parser.add_option('--no_graphics', action='store_true',
                    help='Disable graphics for the vm test.')
  parser.add_option('-j', '--jobs', default=test_helper.CalculateDefaultJobs(),
                    type=int, help='Number of simultaneous jobs')
  parser.add_option('--private_key', default=None,
                    help='Path to the private key used to sign payloads with.')
  parser.add_option('-q', '--quick_test', default=False, action='store_true',
                    help='Use a basic test to verify image.')
  parser.add_option('-m', '--remote',
                    help='Remote address for real test.')
  parser.add_option('-t', '--target_image',
                    help='path to the target image.')
  parser.add_option('--test_results_root', default=None,
                    help='Root directory to store test results.  Should '
                    'be defined relative to chroot root.')
  parser.add_option('--test_prefix', default='test',
                    help='Only runs tests with specific prefix i.e. '
                    'testFullUpdateWipeStateful.')
  parser.add_option('-p', '--type', default='vm',
                    help='type of test to run: [vm, real]. Default: vm.')
  parser.add_option('--verbose', default=True, action='store_true',
                    help='Print out rather than capture output as much as '
                    'possible.')
  parser.add_option('--whitelist_chrome_crashes', default=False,
                    dest='whitelist_chrome_crashes', action='store_true',
                    help='Treat Chrome crashes as non-fatal.')
  (options, leftover_args) = parser.parse_args()

  CheckOptions(parser, options, leftover_args)

  # Generate cache of updates to use during test harness.
  update_cache = _ReadUpdateCache(options.target_image)
  if not update_cache:
    cros_lib.Info('No update cache found. Update testing will not work.  Run'
                  ' cros_generate_update_payloads if this was not intended.')

  # Create download folder for payloads for testing.
  download_folder = os.path.join(os.path.realpath(os.path.curdir),
                                 'latest_download')
  if not os.path.exists(download_folder):
    os.makedirs(download_folder)

  au_worker.AUWorker.SetUpdateCache(update_cache)
  my_server = dev_server_wrapper.DevServerWrapper(options.test_results_root)
  my_server.start()
  try:
    my_server.WaitUntilStarted()
    if options.type == 'vm':
      _RunTestsInParallel(options)
    else:
      # TODO(sosa) - Take in a machine pool for a real test.
      # Can't run in parallel with only one remote device.
      test_suite = _PrepareTestSuite(options)
      test_result = unittest.TextTestRunner().run(test_suite)
      if not test_result.wasSuccessful(): cros_lib.Die('Test harness failed.')

  finally:
    my_server.Stop()


if __name__ == '__main__':
  main()
