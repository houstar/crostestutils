#!/usr/bin/python
# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Parses and displays the contents of one or more autoserv result directories.

This script parses the contents of one or more autoserv results folders and
generates test reports.
"""

import datetime
import glob
import optparse
import os
import re
import sys

import constants
sys.path.append(constants.CROSUTILS_LIB_DIR)
from cros_build_lib import Color, Die, Warning

_STDOUT_IS_TTY = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

class CrashWaiver:
  """Represents a crash that we want to ignore for now."""
  def __init__(self, signals, deadline, ignored_url, ignored_person):
    self.signals = signals
    self.deadline = datetime.datetime.strptime(deadline, '%Y-%b-%d')

# List of crashes which are okay to ignore. This list should almost always be
# empty. If you add an entry, include the bug URL and your name, something like
#     'crashy':CrashWaiver(
#       ['sig 11'], '2011-Aug-18', 'http://crosbug/123456', 'developer'),

_CRASH_WHITELIST = {
}


class ResultCollector(object):
  """Collects status and performance data from an autoserv results directory."""

  def __init__(self, collect_perf=True, strip_text=''):
    """Initialize ResultsCollector class.

    Args:
      collect_perf: Should perf keyvals be collected?
      strip_text: Prefix to strip from test directory names.
    """
    self._collect_perf = collect_perf
    self._strip_text = strip_text

  def _CollectPerf(self, testdir):
    """Parses keyval file under testdir.

    If testdir contains a result folder, process the keyval file and return
    a dictionary of perf keyval pairs.

    Args:
      testdir: The autoserv test result directory.

    Returns:
      If the perf option is disabled or the there's no keyval file under
      testdir, returns an empty dictionary. Otherwise, returns a dictionary of
      parsed keyvals. Duplicate keys are uniquified by their instance number.
    """

    perf = {}
    if not self._collect_perf:
      return perf

    keyval_file = os.path.join(testdir, 'results', 'keyval')
    if not os.path.isfile(keyval_file):
      return perf

    instances = {}

    for line in open(keyval_file):
      match = re.search(r'^(.+){perf}=(.+)$', line)
      if match:
        key = match.group(1)
        val = match.group(2)

        # If the same key name was generated multiple times, uniquify all
        # instances other than the first one by adding the instance count
        # to the key name.
        key_inst = key
        instance = instances.get(key, 0)
        if instance:
          key_inst = '%s{%d}' % (key, instance)
        instances[key] = instance + 1

        perf[key_inst] = val

    return perf

  def _CollectResult(self, testdir, results):
    """Adds results stored under testdir to the self._results dictionary.

    If testdir contains 'status.log' or 'status' files, assume it's a test
    result directory and add the results data to the self._results dictionary.
    The test directory name is used as a key into the results dictionary.

    Args:
      testdir: The autoserv test result directory.
      results: Results dictionary to store results in.
    """

    # Autotest makes its own job report for the top-level summary "test".
    # Take advantage of this to ignore the results here and report the
    # name of the suite.
    if os.path.exists(os.path.join(testdir, 'job_report.html')):
      return

    status_file = os.path.join(testdir, 'status.log')
    if not os.path.isfile(status_file):
      status_file = os.path.join(testdir, 'status')
      if not os.path.isfile(status_file):
        return

    status = False
    error_msg = None
    status_raw = open(status_file, 'r').read()
    failures = 'ABORT|ERROR|FAIL|TEST_NA|WARN'
    if (re.search(r'GOOD.+completed successfully', status_raw) and
        not re.search(r'%s' % failures, status_raw)):
      status = True
    else:
      match = re.search(r'^\t+(%s)\t(.+)' % failures, status_raw, re.MULTILINE)
      if match:
        error_msg = ': '.join([match.group(1), match.group(2).split('\t')[4]])

    perf = self._CollectPerf(testdir)

    if testdir.startswith(self._strip_text):
      testdir = testdir.replace(self._strip_text, '', 1)

    crashes = []
    regex = re.compile('Received crash notification for ([-\w]+).+ (sig \d+)')
    for match in regex.finditer(status_raw):
      if match.group(1) in _CRASH_WHITELIST:
        w = _CRASH_WHITELIST[match.group(1)]
        if match.group(2) in w.signals and w.deadline > datetime.datetime.now():
          print 'Ignoring crash in %s for waiver that expires %s' % (
              match.group(1), w.deadline.strftime('%Y-%b-%d'))
          continue
      crashes.append('%s %s' % match.groups())

    results[testdir] = {'crashes': crashes,
                        'status': status,
                        'error_msg': error_msg,
                        'perf': perf}

  def CollectResults(self, resdir):
    """Recursively collect results into a dictionary.

    Args:
      resdir: results/test directory to parse results from and recurse into.

    Returns:
      Dictionary of results.
    """
    results = {}
    self._CollectResult(resdir, results)
    for testdir in glob.glob(os.path.join(resdir, '*')):
      # Remove false positives that are missing a debug dir.
      if not os.path.exists(os.path.join(testdir, 'debug')):
        continue

      results.update(self.CollectResults(testdir))
    return results


class ReportGenerator(object):
  """Collects and displays data from autoserv results directories.

  This class collects status and performance data from one or more autoserv
  result directories and generates test reports.
  """

  _KEYVAL_INDENT = 2
  _STATUS_STRINGS = {'hr':  {'pass': '[  PASSED  ]', 'fail': '[  FAILED  ]'},
                     'csv': {'pass': 'PASS', 'fail': 'FAIL'}}

  def __init__(self, options, args):
    self._options = options
    self._args = args
    self._color = Color(options.color)

  def _CollectResults(self):
    """Parses results into the self._results dictionary.

    Initializes a dictionary (self._results) with test folders as keys and
    result data (status, perf keyvals) as values.
    """
    self._results = {}
    collector = ResultCollector(self._options.perf, self._options.strip)
    for resdir in self._args:
      if not os.path.isdir(resdir):
        Die('\'%s\' does not exist' % resdir)
      self._results.update(collector.CollectResults(resdir))

    if not self._results:
      Die('no test directories found')

  def _GenStatusString(self, status):
    """Given a bool indicating success or failure, return the right string.

    Also takes --csv into account, returns old-style strings if it is set.

    Args:
      status: True or False, indicating success or failure.
    Returns:
      The appropriate string for printing..
    """
    success = 'pass' if status else 'fail'
    if self._options.csv:
      return self._STATUS_STRINGS['csv'][success]
    return self._STATUS_STRINGS['hr'][success]

  def _Indent(self, msg):
    """Given a message, indents it appropriately."""
    return ' ' * self._KEYVAL_INDENT + msg

  def _GetTestColumnWidth(self):
    """Returns the test column width based on the test data.

    Aligns the test results by formatting the test directory entry based on
    the longest test directory or perf key string stored in the self._results
    dictionary.

    Returns:
      The width for the test column.
    """
    width = len(max(self._results, key=len))
    for result in self._results.values():
      perf = result['perf']
      if perf:
        perf_key_width = len(max(perf, key=len))
        width = max(width, perf_key_width + self._KEYVAL_INDENT)
    return width

  def _PrintDashLine(self, width):
    """Prints a line of dashes as a separator in output.

    Args:
      width: an integer.
    """
    if not self._options.csv:
      print ''.ljust(width + len(self._STATUS_STRINGS['hr']['pass']), '-')

  def _PrintEntries(self, entries):
    """Prints a list of strings, delimited based on --csv flag.

    Args:
      entries: a list of strings, entities to output.
    """
    delimiter = ',' if self._options.csv else ' '
    print delimiter.join(entries)

  def _PrintErrors(self, test, error_msg):
    """Prints an indented error message, unless the --csv flag is set.

    Args:
      test: the name of a test with which to prefix the line.
      error_msg: a message to print.  None is allowed, but ignored.
    """
    if not self._options.csv and error_msg:
      self._PrintEntries([test, self._Indent(error_msg)])

  def _PrintErrorLogs(self, test, test_string):
    """Prints the error log for |test| if --debug is set.

    Args:
      test: the name of a test suitable for embedding in a path
      test_string: the name of a test with which to prefix the line.
    """
    if self._options.print_debug:
      debug_file_regex = os.path.join(self._options.strip, test, 'debug',
                                      '%s*.ERROR' % os.path.basename(test))
      for path in glob.glob(debug_file_regex):
        try:
          with open(path) as fh:
            for line in fh:
              if len(line.lstrip()) > 0:  # Ensure line is not just WS.
                self._PrintEntries([test_string, self._Indent(line.rstrip())])
        except:
          print 'Could not open %s' % path

  def _GenerateReportText(self):
    """Prints a result report to stdout.

    Prints a result table to stdout. Each row of the table contains the test
    result directory and the test result (PASS, FAIL). If the perf option is
    enabled, each test entry is followed by perf keyval entries from the test
    results.
    """

    tests = self._results.keys()
    tests.sort()

    width = self._GetTestColumnWidth()

    crashes = {}
    tests_pass = 0
    self._PrintDashLine(width)

    for test in tests:
      test_entry = test if self._options.csv else test.ljust(width)

      result = self._results[test]
      status_entry = self._GenStatusString(result['status'])
      if result['status']:
        color = Color.GREEN
        tests_pass += 1
      else:
        color = Color.RED

      status_entry = self._color.Color(color, status_entry)
      self._PrintEntries([test_entry, status_entry])
      self._PrintErrors(test_entry, result['error_msg'])

      # Print out error log for failed tests.
      if not result['status']:
        self._PrintErrorLogs(test, test_entry)

      # Emit the perf keyvals entries. There will be no entries if the
      # --no-perf option is specified.
      perf = result['perf']
      perf_keys = perf.keys()
      perf_keys.sort()

      for perf_key in perf_keys:
        if self._options.csv:
          perf_key_entry = perf_key
        else:
          perf_key_entry = perf_key.ljust(width - self._KEYVAL_INDENT)
          perf_key_entry = perf_key_entry.rjust(width)
        perf_value_entry = self._color.Color(Color.BOLD, perf[perf_key])
        self._PrintEntries([test_entry, perf_key_entry, perf_value_entry])

      # Determine that there was a crash during this test.
      if result['crashes']:
        for crash in result['crashes']:
          if not crash in crashes:
            crashes[crash] = set([])
          crashes[crash].add(test)

    self._PrintDashLine(width)

    if not self._options.csv:
      total_tests = len(tests)
      percent_pass = 100 * tests_pass / total_tests
      pass_str = '%d/%d (%d%%)' % (tests_pass, total_tests, percent_pass)
      print 'Total PASS: ' + self._color.Color(Color.BOLD, pass_str)

    if self._options.crash_detection:
      print ''
      if crashes:
        print self._color.Color(Color.RED, 'Crashes detected during testing:')
        self._PrintDashLine(width)

        for crash_name, crashed_tests in sorted(crashes.iteritems()):
          print self._color.Color(Color.RED, crash_name)
          for crashed_test in crashed_tests:
            print self._Indent(crashed_test)

        self._PrintDashLine(width)
        print 'Total unique crashes: ' + self._color.Color(Color.BOLD,
                                                           str(len(crashes)))

      # Sometimes the builders exit before these buffers are flushed.
      sys.stderr.flush()
      sys.stdout.flush()

  def Run(self):
    """Runs report generation."""
    self._CollectResults()
    self._GenerateReportText()
    for v in self._results.itervalues():
      if v['status'] != 'PASS' or (self._options.crash_detection
                                   and v['crashes']):
        sys.exit(1)


def main():
  usage = 'Usage: %prog [options] result-directories...'
  parser = optparse.OptionParser(usage=usage)
  parser.add_option('--color', dest='color', action='store_true',
                    default=_STDOUT_IS_TTY,
                    help='Use color for text reports [default if TTY stdout]')
  parser.add_option('--no-color', dest='color', action='store_false',
                    help='Don\'t use color for text reports')
  parser.add_option('--no-crash-detection', dest='crash_detection',
                    action='store_false', default=True,
                    help='Don\'t report crashes or error out when detected')
  parser.add_option('--csv', dest='csv', action='store_true',
                    help='Output test result in CSV format.  '
                    'Implies --no-debug --no-crash-detection.')
  parser.add_option('--perf', dest='perf', action='store_true',
                    default=True,
                    help='Include perf keyvals in the report [default]')
  parser.add_option('--no-perf', dest='perf', action='store_false',
                    help='Don\'t include perf keyvals in the report')
  parser.add_option('--strip', dest='strip', type='string', action='store',
                    default='results.',
                    help='Strip a prefix from test directory names'
                    ' [default: \'%default\']')
  parser.add_option('--no-strip', dest='strip', const='', action='store_const',
                    help='Don\'t strip a prefix from test directory names')
  parser.add_option('--no-debug', dest='print_debug', action='store_false',
                    default=True,
                    help='Don\'t print out logs when tests fail.')
  (options, args) = parser.parse_args()

  if not args:
    parser.print_help()
    Die('no result directories provided')

  if options.csv and (options.print_debug or options.crash_detection):
    Warning('Forcing --no-debug --no-crash-detection')
    options.print_debug = False
    options.crash_detection = False

  generator = ReportGenerator(options, args)
  generator.Run()


if __name__ == '__main__':
  main()
