#!/usr/bin/python
# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Runs tests on VMs in parallel."""

import optparse
import os
import subprocess
import sys
import tempfile

import constants
sys.path.append(constants.SOURCE_ROOT)
from chromite.lib import cros_build_lib


_DEFAULT_BASE_SSH_PORT = 9322

class ParallelTestRunner(object):
  """Runs tests on VMs in parallel.

  This class is a simple wrapper around cros_run_vm_test that provides an easy
  way to spawn several test instances in parallel and aggregate the results when
  the tests complete.  Only uses emerged autotest packaged, as trying to pull
  from the caller's source tree creates races that cause tests to fail.
  """

  def __init__(self, tests, base_ssh_port=_DEFAULT_BASE_SSH_PORT, board=None,
               image_path=None, order_output=False, quiet=False,
               results_dir_root=None):
    """Constructs and initializes the test runner class.

    Args:
      tests: A list of test names (see test_that.py).
      base_ssh_port: The base SSH port. Spawned VMs listen to localhost SSH
        ports incrementally allocated starting from the base one.
      board: The target board. If none, cros_run_vm_tests will use the default
        board.
      image_path: Full path to the VM image. If none, cros_run_vm_tests will use
        the latest image.
      order_output: If True, output of individual VMs will be piped to
        temporary files and emitted at the end.
      quiet: Emits no output from the VMs.  Forces --order_output to be false,
        and requires specifying --results_dir_root
      results_dir_root: The results directory root. If provided, the results
        directory root for each test will be created under it with the SSH port
        appended to the test name.
    """
    self._tests = tests
    self._base_ssh_port = base_ssh_port
    self._board = board
    self._image_path = image_path
    self._order_output = order_output
    self._quiet = quiet
    self._results_dir_root = results_dir_root

  def _SpawnTests(self):
    """Spawns VMs and starts the test runs on them.

    Runs all tests in |self._tests|. Each test is executed on a separate VM.

    Returns:
      A list of test process info objects containing the following dictionary
      entries:
        'test': the test name;
        'proc': the Popen process instance for this test run.
    """
    ssh_port = self._base_ssh_port
    spawned_tests = []
    for test in self._tests:
      # Must run outside the chroot and use src path.
      args = [ os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            '../cros_run_vm_test'),
               '--copy', # The image is shared so don't modify it.
               '--no_graphics',
               '--use_emerged',
               '--verbose=1',
               '--ssh_port=%d' % ssh_port ]
      if self._board: args.append('--board=%s' % self._board)
      if self._image_path: args.append('--image_path=%s' % self._image_path)
      results_dir = None
      if self._results_dir_root:
        results_dir = '%s/%s.%d' % (self._results_dir_root, test, ssh_port)
        args.append('--results_dir_root=%s' % results_dir)
      args.append(test)
      output = None
      if self._quiet:
        args.append('--verbose=0')  # generate less output
        output = open('/dev/null', mode='w')
        cros_build_lib.Info('Log files are in %s', results_dir)
      elif self._order_output:
        output = tempfile.NamedTemporaryFile(prefix='parallel_vm_test_')
        cros_build_lib.Info('Piping output to %s.', output.name)
      cros_build_lib.Info('Running %r...', args)
      proc = subprocess.Popen(args, stdout=output, stderr=output)
      test_info = { 'test': test,
                    'proc': proc,
                    'output': output }
      spawned_tests.append(test_info)
      ssh_port = ssh_port + 1
    return spawned_tests

  def _WaitForCompletion(self, spawned_tests):
    """Waits for tests to complete and returns a list of failed tests.

    If the test output was piped to a file, dumps the file contents to stdout.

    Args:
      spawned_tests: A list of test info objects (see _SpawnTests).

    Returns:
      A list of failed test names.
    """
    failed_tests = []
    for test_info in spawned_tests:
      proc = test_info['proc']
      proc.wait()
      if proc.returncode: failed_tests.append(test_info['test'])
      output = test_info['output']
      if output and not self._quiet:
        test = test_info['test']
        cros_build_lib.Info('------ START %s:%s ------', test, output.name)
        output.seek(0)
        for line in output:
          print line,
        cros_build_lib.Info('------ END %s:%s ------', test, output.name)
    return failed_tests

  def Run(self):
    """Runs the tests in |self._tests| on separate VMs in parallel."""
    spawned_tests = self._SpawnTests()
    failed_tests = self._WaitForCompletion(spawned_tests)
    if failed_tests: cros_build_lib.Die('Tests failed: %r', failed_tests)


def main():
  usage = 'Usage: %prog [options] tests...'
  parser = optparse.OptionParser(usage=usage)
  parser.add_option('--base_ssh_port', type='int',
                    default=_DEFAULT_BASE_SSH_PORT,
                    help='Base SSH port. Spawned VMs listen to localhost SSH '
                    'ports incrementally allocated starting from the base one. '
                    '[default: %default]')
  parser.add_option('--board',
                    help='The target board. If none specified, '
                    'cros_run_vm_test will use the default board.')
  parser.add_option('--image_path',
                    help='Full path to the VM image. If none specified, '
                    'cros_run_vm_test will use the latest image.')
  parser.add_option('--order_output', action='store_true', default=False,
                    help='Rather than emitting interleaved progress output '
                    'from the individual VMs, accumulate the outputs in '
                    'temporary files and dump them at the end.')
  parser.add_option('--quiet', action='store_true', default=False,
                    help='Emits no output from the VMs.  Forces --order_output'
                    'to be false, and requires specifying --results_dir_root')
  parser.add_option('--results_dir_root',
                    help='Root results directory. If none specified, each test '
                    'will store its results in a separate /tmp directory.')
  (options, args) = parser.parse_args()

  if not args:
    parser.print_help()
    cros_build_lib.Die('no tests provided')

  if options.quiet:
    options.order_output = False
    if not options.results_dir_root:
      cros_build_lib.Die('--quiet requires --results_dir_root')
  runner = ParallelTestRunner(args, options.base_ssh_port, options.board,
                              options.image_path, options.order_output,
                              options.quiet, options.results_dir_root)
  runner.Run()


if __name__ == '__main__':
  cros_build_lib.SetupBasicLogging()
  main()
