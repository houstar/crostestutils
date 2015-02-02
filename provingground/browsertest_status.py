#!/usr/bin/python
# Copyright (c) 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Script to display latest test run status and test results for a user-
# specified list of browser_tests. The names of the desired brower_tests are
# read from a file located (by default) in the same directory as this script.
#
# Latest test run status is fetched from the build.chromium.org build server,
# read from the 'stdio' text file located at:
#   http://build.chromium.org/p/chromium.chromiumos/builders/TR_BUILDER/
#   builds/BUILD_NUMBER/steps/browser_tests/logs/stdio/text
#
# Recent test results are fetched from the test-results.appspot.com server,
# read from the results.json file located at:
#   https://test-results.appspot.com/testfile?master=ChromiumChromiumOS&
#   builder=Linux ChromiumOS Tests (2)&testtype=browser_tests&
#   name=results.json
#

"""Script to report test status and results of user-specified browsertests."""
__author__ = ('scunningham@google.com Scott Cunningham')

import argparse
import json
import os
import re
import sys
import urllib2

# Chromium builder url parameter defaults.
_BUILD_HOST = 'build.chromium.org'
_BUILD_PROJECT = 'chromium.chromiumos'
_BUILD_NUMBER = '-2'
_TEST_TYPE = 'browser_tests'

# TestResults server url parameter defaults.
_TR_HOST = 'test-results.appspot.com'  # URI to TestResults server.
_TR_MASTER = 'ChromiumChromiumOS'  # Test-results build master repository.
_TR_BUILDER = 'Linux ChromiumOS Tests (dbg)(1)'  # TestResults builder name.

# Input file and report directory parameter defaults.
_TESTS_FILE = './tests'  # Path to the file that contains the tests names.
_REPORT_DIR = os.getcwd()  # Path to the directory to store the results report.

# Contents of test result types.
_RESULT_TYPES = {
    'A': 'AUDIO',
    'C': 'CRASH',
    'F': 'TEXT',
    'I': 'IMAGE',
    'L': 'FLAKY',
    'O': 'MISSING',
    'N': 'NO DATA',
    'Q': 'FAIL',
    'P': 'PASS',
    'T': 'TIMEOUT',
    'Y': 'NOTRUN',
    'X': 'SKIP',
    'Z': 'IMAGE+TEXT'
    }

# Report header result types.
_NOTRUN = 'NotRun'
_FAILED = 'Failed'
_PASSED = 'Passed'
_MISSING = 'Missing'


def _FindLatestCompletedBuildNumber(build_number):
  """Find the latest completed build number from the given build number.

  Check if build with build_number completed successfully. If not, iteratively
  check earlier versions, until a successfully completed build is found.

  Args:
    build_number: build number to start search.

  Returns:
    Build number of most recent successfully completed build.
  """
  # TODO(scunningham): Implement a real find function in later version.
  return build_number


def _GetStdioLogUrl(builder, build_num, test_type):
  """Get url to Stdio Log file from builder for build number.

  Args:
    builder: Builder name.
    build_num: Build number.
    test_type: Type of browser test.

  Returns:
    Url to the Stdio log text file.
  """
  # Generate percent-encoded build url.
  build_url = (('http://%s/p/%s/json/builders/%s/builds?'
                'select=%s/steps/%s/') %
               (urllib2.quote(_BUILD_HOST), urllib2.quote(_BUILD_PROJECT),
                urllib2.quote(builder), urllib2.quote(build_num),
                urllib2.quote(test_type)))

  # Fetch build status file from build url.
  print '\nFetching build status file from: %s' % build_url
  url = urllib2.urlopen(build_url)
  build_status_file = url.read()
  url.close()

  # Convert json build status file to dictionary.
  build_status_dict = json.loads(build_status_file)

  # Extract stdio log url from build status dictionary.
  print '\n  Contents of build status file: %s' % build_status_dict
  return build_status_dict[build_num]['steps'][test_type]['logs'][0][1]


def _GetStdioLogTestsDict(stdio_url):
  """Get Stdio Log browser_tests from the given url.

  Args:
    stdio_url: url to stdio log browser_tests file.

  Returns:
    Dictionary of tests from stdio log browser_tests text file.
  """
  # Fetch builder stdio log text file from url.
  stdio_text_url = stdio_url+'/text'
  print '\nFetching builder stdio log file from: %s' % stdio_text_url
  stdio_text_file = urllib2.urlopen(stdio_text_url)

  # Extract test lines from stdio text file.
  pattern = r'\[\d+/\d+\] '
  test_lines = [line for line in stdio_text_file if re.match(pattern, line)]
  stdio_text_file.close()
  print '  Total run tests extracted: %s' % len(test_lines)
  if test_lines:
    print '  Last run test line: "%s"' % test_lines[-1].strip()

  # Extract test data and pack into stdio tests dictionary.
  stdio_tests_dict = {}
  pattern = r'(\[\d*/\d*\]) (.*?) (\(.*\))'
  for i, line in enumerate(test_lines):
    m = re.match(pattern, line)
    if m:
      stdio_tests_dict[m.group(2)] = (m.group(1), m.group(3))
    else:
      print 'Error: Invalid test line %s) %s' % (i, line.strip())

  return stdio_tests_dict


def _GetUserSpecifiedTests(tests_file):
  """Get list of user-specified tests from tests file.

  File must be a text file, formatted with one line per test. Leading and
  trailing spaces and blanklines are stripped from the test list. If a line
  still contains a space return only the first word (to remove comments).

  Args:
    tests_file: Path and name of tests file.

  Returns:
    List of user tests read from lines in the tests_file.
  """
  print '\nFetching user-specified tests from: %s' % tests_file
  content = open(tests_file, 'r').read().strip()
  return [line.strip().split()[0] for line in content.splitlines()
          if line.strip()]


def _RunAndNotrunTests(stdio_tests, user_tests):
  """Return lists of individual test instances of user-specified tests.

  The first list is of test instances present in the stdio tests list.
  Presence indicates that the test instance was run on the build. Second list
  is tests that are absent from the stdio tests list. Absence means that no
  instance of the test was run on the build.

  Note that there can be multiple instances of a user-specified test run on a
  build if a) The test belongs to test group, and b) the test was run with
  multiple test data values. This function uses a regex to search for multiple
  instances of tests that match the user-specifed test name.

  Args:
    stdio_tests: List of test instances run on build.
    user_tests: List of test names specified by user.

  Returns:
  1) run_tests: list of test instances of user tests run on build.
  2) notrun_tests: list of user tests not run on build.
  """
  run_user_tests = []
  notrun_user_tests = []
  for user_test in user_tests:
    pattern = r'(.*/)?%s(/\d*)?$' % user_test
    found_run_test = False
    for stdio_test in stdio_tests:
      if re.search(pattern, stdio_test):
        found_run_test = True
        run_user_tests.append(stdio_test)
    if not found_run_test:
      notrun_user_tests.append(user_test)
  print '  Run instances of user tests: %s' % len(run_user_tests)
  print '  Not run user tests: %s\n' % len(notrun_user_tests)
  return run_user_tests, notrun_user_tests


def _GetResultsDict(master, builder, test_type):
  """Get results dictionary from builder results.json file.

  The results dictionary contains information about recent tests run,
  test results, build numbers, chrome revision numbers, etc, for the
  last 500 builds on the specified builder.

  Args:
    master: Master repo (e.g., 'ChromiumChromiumOS')
    builder: Builder name (e.g., 'Linux ChromiumOS Tests (2)')
    test_type: Type of browser test.

  Returns:
    Dictionary of builder results.
  """
  # Generate percent-encoded builder results url.
  results_url = (('https://%s/testfile?master=%s&builder=%s'
                  '&testtype=%s&name=results.json') %
                 (urllib2.quote(_TR_HOST), urllib2.quote(master),
                  urllib2.quote(builder), urllib2.quote(test_type)))

  # Fetch results file from builder results url.
  print 'Fetching builder results file from %s' % results_url
  url = urllib2.urlopen(results_url)
  results_json = url.read()
  url.close()

  # Convert json results to native Python object.
  builder_results_dict = json.loads(results_json)
  return builder_results_dict[builder]


def _CreateTestsResultsDictionary(builder_tests_dict):
  """Create dictionary of all tests+results from builder tests dictionary.

  Parse individual tests and results from the builder tests dictionary,
  and place into a flattened tests results dictionary. Most tests are
  standalone, and keyed by thier test name. Some tests belong to a
  'testinstance' group, and are keyed by their testinstance name, the
  test data value (e.g., '0', '1', '2'), and the test name.

  For example, a standalone test:result is formatted thus:
  "BookmarksTest.CommandOpensBookmarksTab": {
    "results": [...]
    "times": [...]
  }

  Tests grouped under a testinstance, are formatted thus:
  "MediaStreamDevicesControllerBrowserTestInstance": {
    "MediaStreamDevicesControllerBrowserTest.AudioCaptureAllowed": {
      "1": {
        "results": [...],
        "times": [...]
      }
    "MediaStreamDevicesControllerBrowserTest.VideoCaptureAllowed": {
      "0": {
        "results": [...],
        "times": [...]
      }
    }

  Args:
    builder_tests_dict: Dictionary of test groups & tests on builder.

  Returns:
    Dictionary of flattened tests and their results on builder.
  """
  tests_results_dict = {}
  standalone = 0
  group = 0
  subtest = 0

  for group_name in builder_tests_dict:
    test_group = builder_tests_dict[group_name]
    if '.' in group_name:
      standalone += 1
      test_result = test_group['results']
      tests_results_dict[group_name] = test_result
    else:
      group += 1
      for test_name in test_group.keys():
        test_values = test_group[test_name]
        for value in test_values.keys():
          subtest += 1
          test_result = test_values[value]['results']
          long_test_name = '%s/%s/%s' % (group_name, test_name, value)
          tests_results_dict[long_test_name] = test_result

  print '  Number of standalone tests: %s' % standalone
  print '  Number of instance tests (in %s groups): %s' % (group, subtest)
  print '  Total tests results: %s\n' % len(tests_results_dict)

  return tests_results_dict


def _CreateUserTestsResultsDict(test_results_dict, run_user_tests):
  """Create dictionary of tests:results for all user-specified tests.

  If a user specified test is missing from builder test+results, then default
  the test result to the code for missing test: 'O'.

  Args:
    test_results_dict: Builder tests+results dictionary
    run_user_tests: List of run instances of user specified tests.

  Returns:
    Dictionary of tests to results for all user specified tests.
  """
  user_tests_results_dict = {}
  # Iterate over run user-specified tests.
  for test_name in run_user_tests:
    if test_name in test_results_dict:  # Test has results.
      test_result = test_results_dict[test_name]
    else:
      test_result = [[999, u'O']]  # Set result to missing.
    user_tests_results_dict[test_name] = test_result

  return user_tests_results_dict


def _CreateResultOfTestsDict(user_tests_results_dict):
  """Create dictionary of user tests keyed by result.

  Args:
    user_tests_results_dict: dictionary of user tests to results.

  Returns:
    Dictionary of results of tests.
  """
  # Test result type lists.
  missing = ['O']
  passed = ['P']
  fails = [key for key in _RESULT_TYPES if key not in missing+passed]

  failed_tests = []
  passed_tests = []
  missing_tests = []
  for test in user_tests_results_dict:
    result = user_tests_results_dict[test][0][1]
    if result in fails:
      failed_tests.append(test)
    elif result in passed:
      passed_tests.append(test)
    elif result in missing:
      missing_tests.append(test)
  return {_FAILED: failed_tests,
          _PASSED: passed_tests,
          _MISSING: missing_tests}


def _ReportTestsByResult(result_of_tests_dict, tr_dict, report_dir):
  """Print and write report of tests, grouped by result type.

  Args:
    result_of_tests_dict: Dictionary of results for tests.
    tr_dict: Dictionary of tests to results for builder.
    report_dir: Directory where to save report.
  """
  # Test report result types and section headers.
  report_results_headers = {
      _NOTRUN: 'Test Status: Not Run',
      _FAILED: 'Test Result: Fail or other Error',
      _PASSED: 'Test Result: Passed recently',
      _MISSING: 'Test Result: Passing long-term'
  }
  report_section_order = [_NOTRUN, _FAILED, _PASSED, _MISSING]

  ofile = open(report_dir+'/report', 'w')
  for result_type in report_section_order:
    header = report_results_headers[result_type]
    tests = result_of_tests_dict[result_type]
    print '%s (%s)' % (header, len(tests))
    ofile.write('%s (%s)\n' % (header, len(tests)))
    for num, test_name in enumerate(sorted(tests)):
      if test_name in tr_dict:
        print '  %s) %s: %s' % (num+1, test_name, tr_dict[test_name][0:2])
        ofile.write('  %s) %s: %s\n' % (num+1, test_name, tr_dict[test_name]))
      else:
        print '  %s) %s' % (num+1, test_name)
        ofile.write('  %s) %s\n' % (num+1, test_name))
  ofile.close()


def main():
  """Report test results of specified browsertests."""
  parser = argparse.ArgumentParser(
      description=('Report run status and test results for a user-specified '
                   'list of browser_test tests.'),
      formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('--tests_file', dest='tests_file', default=_TESTS_FILE,
                      help=('Specify tests path/file '
                            '(default is %s).' % _TESTS_FILE))
  parser.add_argument('--report_dir', dest='report_dir', default=_REPORT_DIR,
                      help=('Specify path to report directory '
                            '(default is %s).' % _REPORT_DIR))
  parser.add_argument('--master', dest='master', default=_TR_MASTER,
                      help=('Specify build master repository '
                            '(default is %s).' % _TR_MASTER))
  parser.add_argument('--builder', dest='builder', default=_TR_BUILDER,
                      help=('Specify test builder '
                            '(default is %s).' % _TR_BUILDER))
  parser.add_argument('--build_num', dest='build_num', default=_BUILD_NUMBER,
                      help=('Specify builder build number '
                            '(default is %s).' % _BUILD_NUMBER))
  parser.add_argument('--test_type', dest='test_type', default=_TEST_TYPE,
                      help=('Specify test type '
                            '(default is %s).' % _TEST_TYPE))
  parser.add_argument('--print_types', dest='print_types',
                      action='store_true', help='Print test result types.')
  arguments = parser.parse_args()

  # Set parameters from command line arguments.
  tests_file = arguments.tests_file
  report_dir = arguments.report_dir
  master = arguments.master
  builder = arguments.builder
  build_num = arguments.build_num
  test_type = arguments.test_type
  print_types = arguments.print_types

  # Print map of test result types.
  if print_types:
    print 'Test result types:'
    print json.dumps(_RESULT_TYPES, indent=4)
    sys.exit()

  # Ensure default or user defined tests file points to a real file.
  if not os.path.isfile(tests_file):
    print 'Error: Could not find tests file. Try passing in --tests_file.'
    sys.exit(2)

  # Ensure default or user-defined report folder points to a real dir.
  if not os.path.exists(report_dir):
    print ('Error: Could not find report directory. '
           'Try passing in --report_dir.')
    sys.exit(2)

  # Get builder stdio log test info for build number.
  # Find latest completed build number.
  if build_num == '0' or build_num == '-1':
    print ('Error: Invalid build number: %s. '
           'Using %s instead.' % (build_num, _BUILD_NUMBER))
    build_num = _BUILD_NUMBER
  completed_build_num = _FindLatestCompletedBuildNumber(build_num)

  # Get list of test instances run on builder for build number.
  stdio_log_url = _GetStdioLogUrl(builder, completed_build_num, test_type)
  stdio_tests_dict = _GetStdioLogTestsDict(stdio_log_url)

  # Read list of user-specified tests from tests file.
  user_tests = _GetUserSpecifiedTests(tests_file)
  if not user_tests:
    print 'Error: tests file is empty.'
    sys.exit(2)
  print '  Number of user tests: %s' % len(user_tests)

  # Get list of instances of run and not run user tests.
  run_user_tests, notrun_user_tests = (
      _RunAndNotrunTests(stdio_tests_dict, user_tests))

  # Get run user tests and results data from the specified builder.
  if run_user_tests:
    # Fetch builder results dictionary from test-results server.
    builder_results_dict = _GetResultsDict(master, builder, test_type)
    builder_tests_dict = builder_results_dict['tests']
  else:
    builder_tests_dict = {}

  # Extract tests to results dictionary from builder tests dictionary.
  tests_results_dict = _CreateTestsResultsDictionary(builder_tests_dict)

  # Create dictionary of run user test instances and results.
  user_tests_results_dict = (
      _CreateUserTestsResultsDict(tests_results_dict, run_user_tests))

  # Create dictionary of run tests that are failed, passed, and missing.
  result_of_tests_dict = _CreateResultOfTestsDict(user_tests_results_dict)

  # Add list of not run tests to the result of tests dictionary.
  result_of_tests_dict[_NOTRUN] = notrun_user_tests

  # Output tests by result type: notrun, failed, passed, and missing.
  _ReportTestsByResult(result_of_tests_dict, tests_results_dict, report_dir)

if __name__ == '__main__':
  main()
