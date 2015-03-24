#!/usr/bin/python2
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Script to display latest test run status and test results for a user-
# specified list of browsertests. The names of the desired browertests are
# read from a file located (by default) in the same directory as this script.
#
# Latest test run status for a build is fetched from the builder, read from
# the 'stdio' text file located at:
#   http://BUILDER_HOST/p/BUILDER_PROJECT/builders/BUILDER_NAME/
#   builds/BUILD_NUMBER/steps/TEST_TYPE/logs/stdio/text
#
# Recent test results history are fetched from the test-results server, read
# from the results.json file located at:
#   https://TR_HOST/testfile?master=TR_MASTER&builder=BUILDER_NAME
#   &testtype=TEST_TYPE&name=results.json
#

"""Script to report test status and results of user-specified browsertests."""

from __future__ import print_function

import argparse
import json
import os
import re
import sys
import urllib2

__author__ = 'scunningham@google.com (Scott Cunningham)'

# Builder url parameter defaults.
_BUILDER_HOST = 'chromegw.corp.google.com'  # Host name of Builder.
_BUILDER_PROJECT = 'chromeos.chrome'  # Project name of Builder.
_BUILDER_NAME = 'Linux ChromeOS Buildspec Tests'  # Builder name.
_BUILD_NUMBER = -1
_TEST_TYPE = 'browser_tests'

# Test-results server url parameter defaults.
_TR_HOST = 'test-results.appspot.com'  # Host name of test-results server.
_TR_MASTER = 'ChromiumChromiumOS'  # Project master of test-results server.

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


def _GetUserSpecifiedTests(tests_file):
  """Get list of user-specified tests from the given tests_file.

  File must be a text file, formatted with one line per test. Leading and
  trailing spaces and blanklines are stripped from the test list. If a line
  still contains a space return only the first word (to remove comments).

  Args:
    tests_file: Path and name of tests file.

  Returns:
    List of user tests read from lines in the tests_file.
  """
  print('\nReading user-specified tests from: %s' % tests_file)
  content = open(tests_file, 'r').read().strip()
  user_tests = [line.strip().split()[0] for line in content.splitlines()
                if line.strip()]
  if not user_tests:
    print('Error: tests file is empty.')
    sys.exit(2)
  print('  Number of user tests: %s' % len(user_tests))

  return user_tests


def _GetBuildsList(build_dict):
  """Get list of available (cached) builds on the builder.

  Args:
    build_dict: build info: builder host, project, and name.

  Returns:
    List of builds available on builder.
  """
  # Generate percent-encoded builder url.
  builder_url = ('https://%s/p/%s/json/builders/%s' %
                 (urllib2.quote(build_dict['builder_host']),
                  urllib2.quote(build_dict['builder_proj']),
                  urllib2.quote(build_dict['builder_name'])))

  # Fetch builder status file from builder url.
  print('\nFetching builder status file from: %s' % builder_url)
  try:
    response = urllib2.urlopen(builder_url)
    builder_status_file = response.read()
    response.close()
  except urllib2.HTTPError as err:
    print('HTTP error: %s' % err)
    sys.exit(2)
  except urllib2.URLError as err:
    print('Notice: Builder was not available: %s' % err)
    sys.exit(2)

  # Convert json builder status file to dictionary.
  builder_status_dict = json.loads(builder_status_file)
  build_list = builder_status_dict['cachedBuilds']
  print('\nList of avaiable builds: %s\n' % build_list)
  return build_list


def _FindBuildByChromiumVersion(build_dict):
  """Find the latest completed build with the given chromium version.

  Search from the top of the cached build list for a build with the given
  chromium |version| number as it's buildspec_version. If found, return the
  build number. If no build is found containing the |version|, return None.

  Args:
    build_dict: build info, with chromium version number.

  Returns:
    Number of most recent build containing the given chromium version.
  """
  # TODO(scunningham): Implement real function in later version.
  cr_version = build_dict['cr_version']
  if cr_version:
    pass
  return _BUILD_NUMBER


def _GetNominalBuildNumber(build_num, builds_list):
  """Verify the build number is in the available builds list.

  If the user-specified |build_num| is negative, then verify it is a valid
  ordinal index, and get the nominal build number for that index. If it is
  positive, then verify the nominal build number exists in the |builds_list|.
  Return the nominal build number. Note that if a build number is available
  does not mean that the build is valid or completed.

  Args:
    build_num: nominal build number (positive) or ordinal index (negative).
    builds_list: List of available build numbers on the builder.

  Returns:
    Nominal build number in |builds_list|.
  """
  # Verify that build number exists in the builds list.
  if build_num < 0:  # User entered an index, not a build number.
    if len(builds_list) < -build_num:
      print('Error: The build_num index %s is too large.' % build_num)
      sys.exit(2)
    build_number = builds_list[build_num]
    print('\n  Index %s selects build %s' % (build_num, build_number))
    build_num = build_number
  elif build_num not in builds_list:
    print('Error: build %s is not available.' % build_num)
    sys.exit(2)
  return build_num


def _LatestCompletedBuild(build_dict, builds_list):
  """Find the latest completed build number from the given list of builds.

  Check each build in the |builds_list|, starting with the build number in
  the given |build_dict|, to determine if the build completed successfully.
  If completed successfully, return the number of the build. If not, continue
  checking. If none of the builds completed successfully, exits.

  Args:
    build_dict: build info dictionary, with build number to start search.
    builds_list: List of cached build numbers on the builder.

  Returns:
    Build number of the latest successfully completed build, and the build
    test status dictionary of that build.
  """
  # Find the latest completed build, starting from build_num.
  build_num = build_dict['build_num']
  starting_build_num = build_num
  starting_build_num_failed = False
  starting_build_index = builds_list.index(starting_build_num)
  for build_num in reversed(builds_list[0:starting_build_index+1]):
    build_test_status_dict = _BuildIsCompleted(build_dict, build_num)
    if build_test_status_dict is not None:
      break
    starting_build_num_failed = True
  else:
    print('No completed builds are available.')
    sys.exit(2)
  if starting_build_num_failed:
    print('\nError: Requested build_num %s was not completed successfully.' %
          starting_build_num)
  print('Using latest successfully completed build: %s\n' % build_num)
  return build_num, build_test_status_dict


def _BuildIsCompleted(build_dict, build_num):
  """Determine whether build was completed successfully.

  Get the build test status. Check whether the build given by |build_num]
  was terminated by an error, or is not finished building. If so, return
  None. Otherwise, return the build test status dictionary.

  Args:
    build_dict: build info dictionary.
    build_num: build number to check.

  Returns:
    Dictionary of build test status if build is completed. Otherwise, None.
  """

  # Copy original build_dict, and point copy to |build_num|.
  temp_build_dict = dict(build_dict)
  temp_build_dict['build_num'] = build_num

  # Get build test status dictionary from builder for |build_num|.
  build_test_status_dict = _GetBuildTestStatus(temp_build_dict)
  steps_dict = build_test_status_dict[str(build_num)]['steps']
  test_type_dict = steps_dict[build_dict['test_type']]

  # Check if build failed or threw an exception:
  if 'error' in test_type_dict:
    return None

  # Check isFinished status in test_type_dict.
  if test_type_dict['isFinished']:
    return build_test_status_dict

  return None


def _GetBuildTestStatus(build_dict):
  """Get the build test status for the given build.

  Fetch the build test status file from the builder for the build number,
  specified in the build info dictionary given by |build_dict|.

  Args:
    build_dict: Build info dictionary.

  Returns:
    Build Test Status dictionary.
  """
  # Generate percent-encoded build test status url.
  build_url = (('https://%s/p/%s/json/builders/%s/builds?'
                'select=%s/steps/%s/') %
               (urllib2.quote(build_dict['builder_host']),
                urllib2.quote(build_dict['builder_proj']),
                urllib2.quote(build_dict['builder_name']),
                build_dict['build_num'],
                urllib2.quote(build_dict['test_type'])))
  print('Fetching build test status file from: %s' % build_url)
  return _FetchStatusFromUrl(build_dict, build_url)


def _GetBuildStatus(build_dict):
  """Get the build status for the given build.

  Fetch the build status file from the builder for the build number, specified
  in the build info dictionary given by |build_dict|.

  Args:
    build_dict: Build info dictionary.

  Returns:
    Build Status dictionary.
  """
  # Generate percent-encoded build status url.
  build_url = (('https://%s/p/%s/json/builders/%s/builds/%s') %
               (urllib2.quote(build_dict['builder_host']),
                urllib2.quote(build_dict['builder_proj']),
                urllib2.quote(build_dict['builder_name']),
                build_dict['build_num']))
  print('Fetching build status file from: %s' % build_url)
  return _FetchStatusFromUrl(build_dict, build_url)


def _FetchStatusFromUrl(build_dict, build_url):
  """Get the status from the given URL.

  Args:
    build_dict: Build info dictionary.
    build_url: URL to the status json file.

  Returns:
    Status dictionary.
  """
  # Fetch json status file from build url.
  hosted_url = _SetUrlHost(build_url, build_dict['builder_host'])
  url = urllib2.urlopen(hosted_url)
  status_file = url.read()
  url.close()

  # Convert json status file to dictionary.
  status_dict = json.loads(status_file)
  return status_dict


def _PrintChromiumVersion(build_properties):
  """Get and print the version number of chromium used in the build.

  Args:
    build_properties: The properties dictionary for the build.

  Returns:
    A string containing the chromium version.
  """
  for property_list in build_properties:
    if 'buildspec_version' in property_list:
      chromium_version = property_list[1]
      print('  Chromium version: %s' % chromium_version)
      break
  else:
    chromium_version = None
    print('  Warning: Build properties has no chromium version.')
  return chromium_version


def _GetTestsFailedList(build_dict, build_status_dict):
  """Get list of failed tests for given build.

  Extract test status summary, including number of tests disabled, flaky, and
  failed, from the test step in |build_status_dict|. If the test step was
  finished, then create a list of tests that failed from the failures string.

  Args:
    build_dict: Build info dictionary.
    build_status_dict: Build status dictionary.

  Returns:
    List of tests that failed.
  """
  # Get test type from build_dict and tests steps from build_status_dict.
  test_type = build_dict['test_type']
  build_steps = build_status_dict['steps']

  # Get count of disabled, flaky, failed, and test failures.
  num_tests_disabled = 0
  num_tests_flaky = 0
  num_tests_failed = 0
  test_failures = ''

  for step_dict in build_steps:
    text_list = step_dict['text']
    if test_type in text_list:
      for item in text_list:
        m = re.match(r'(\d+) disabled', item)
        if m:
          num_tests_disabled = m.group(1)
          continue
        m = re.match(r'(\d+) flaky', item)
        if m:
          num_tests_flaky = m.group(1)
          continue
        m = re.match(r'failed (\d+)', item)
        if m:
          num_tests_failed = m.group(1)
          continue
        m = re.match(r'<br\/>failures:<br\/>(.*)<br\/>', item)
        if m:
          test_failures = m.group(1)
          continue
      break #  Exit step_dict loop if test_type is in text_list.
    is_finished = step_dict['isFinished']
  else:
    print('Error: build_steps has no \'%s\' step.' % test_type)
    is_finished = 'Error'

  # Split the test_failures into a tests_failed_list.
  tests_failed_list = []
  if num_tests_failed:
    tests_failed_list = test_failures.split('<br/>')

  print('  Test finished: %s' % is_finished)
  print('  Disabled: %s' % num_tests_disabled)
  print('  Flaky: %s' % num_tests_flaky)
  print('  Failed: %s : %s' % (num_tests_failed, tests_failed_list))

  return tests_failed_list


def _GetStdioLogUrlFromBuildStatus(build_dict, build_test_status_dict):
  """Get url to Stdio Log file from given build test status dictionary.

  Args:
    build_dict: Build info dictionary.
    build_test_status_dict: Build Test Status dictionary.

  Returns:
    Url to the Stdio Log text file.
  """

  steps_dict = build_test_status_dict[str(build_dict['build_num'])]['steps']
  test_type_dict = steps_dict[build_dict['test_type']]

  if 'error' in test_type_dict:
    return None

  log_url = test_type_dict['logs'][0][1]
  stdio_log_url = _SetUrlHost(log_url, build_dict['builder_host'])+'/text'
  return stdio_log_url


def _GetStdioLogTests(stdio_log_url, tests_failed_list):
  """Get Stdio Log Tests from the given url.

    Extracts tests from the stdio log file of the builder referenced by
    |stdio_log_url|, and packs them into a stdio tests dictionary. This
    dictionary uses the long test name as the key, and the value is a list
    that contains the test result. We use a list for the test result to mirror
    the format used by the test-result server.

    If a test is in the |tests_failed_list|, then set the test result to the
    the failure code: 'Q'. Otherwise, set result to the pass code: 'P'. The
    result repetition count of '999' is a placeholder that indicates that the
    value is not from the test-result server.

    Here is the format of the dictionary:
    {
      MaybeSetMetadata/SafeBrowseService.MalwareImg/1: [[999, 'P']],
      MaybeSetMetadata/SafeBrowseService.MalwareImg/2: [[999, 'Q']],
      PlatformAppBrowserTest.ComponentBackgroundPage: [[999, 'P']],
      NoSessionRestoreTest.LocalStorageClearedOnExit: [[999, 'P']]
    }

  Args:
    stdio_log_url: url to stdio log tests text file.
    tests_failed_list: list of failed tests, from the build status page.

  Returns:
    Dictionary of test instances from stdio log tests text file.
  """
  # Fetch builder stdio log text file from url.
  print('\nFetching builder stdio log file from: %s' % stdio_log_url)
  stdio_text_file = urllib2.urlopen(stdio_log_url)

  # Extract test lines from stdio log text file to test_lines dictionary.
  p_test = r'\[\d*/\d*\] (.*?) \(.*\)'
  p_exit = r'exit code \(as seen by runtest.py\)\: (\d+)'
  test_lines = []
  exit_flag = False
  exit_code = None

  for line in stdio_text_file:
    if not exit_flag:
      m = re.match(p_test, line)
      if m:
        if line not in test_lines:
          test_lines.append(line)
      m = re.match(p_exit, line)
      if m:
        exit_flag = True
        exit_code = m.group(1)
  stdio_text_file.close()
  print('  Total run tests extracted: %s' % len(test_lines))
  if test_lines:
    print('  Last run test line: "%s"' % test_lines[-1].strip())

  # Extract test_lines data and pack into stdio tests dictionary.
  stdio_tests_dict = {}
  for i, line in enumerate(test_lines):
    m = re.match(p_test, line)
    if m:
      long_test_name = m.group(1)
      if long_test_name in tests_failed_list:
        test_result = [[999, u'Q']]  # Test result Failed code 'Q'.
      else:
        test_result = [[999, u'P']]  # Test result Passed code 'P'.
      stdio_tests_dict[long_test_name] = test_result
    else:
      print('Error: Invalid test line %s) %s' % (i, line.strip()))

  print('  Test Exit Code: %s' % exit_code)
  return stdio_tests_dict


def _RunAndNotrunTests(stdio_tests, user_tests):
  """Return lists of run and not-run instances of given user tests.

  The first list is of test instances present in the |stdio_tests| list.
  Presence indicates that the test instance was run on the build. The second
  list is tests that are absent from the |stdio_tests| list. Absence means
  that no instance of the test was run on the build.

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
    pattern = r'(.*/)?%s(/\d*)?$' % user_test  # pattern for test name.
    found_run_test = False
    for stdio_test in stdio_tests:
      if re.search(pattern, stdio_test):
        found_run_test = True
        run_user_tests.append(stdio_test)
    if not found_run_test:
      notrun_user_tests.append(user_test)
  print('  User tests: Instances run: %s' % len(run_user_tests))
  print('  User tests: Not run: %s\n' % len(notrun_user_tests))
  return run_user_tests, notrun_user_tests


def _GetTestResultsJson(master, builder_name, test_type):
  """Get test results data from results.json file for the builder.

  The results.json file contains historical data about the tests run on the
  given |builder_name| for the most recent (up to the last 500) builds. The
  data includes test names, test result codes, build numbers, and chrome
  revision numbers.

  Args:
    master: Master repo (e.g., 'ChromiumChromiumOS')
    builder_name: Builder name (e.g., 'Linux ChromiumOS Tests (dbg)(1)')
    test_type: Type of browsertests: browser_tests or interactive_ui_tests

  Returns:
    Contents of the results.json file from the test-result server for the
    specified builder.
  """
  # Generate percent-encoded test results url for specified builder.
  results_url = (('https://%s/testfile?master=%s&builder=%s'
                  '&testtype=%s&name=results.json') %
                 (urllib2.quote(_TR_HOST), urllib2.quote(master),
                  urllib2.quote(builder_name), urllib2.quote(test_type)))

  # Fetch results file from test results url.
  print('Fetching test results file from %s' % results_url)
  try:
    url = urllib2.urlopen(results_url)
    results_json = url.read()
    url.close()
  except urllib2.HTTPError:
    results_json = None
    print(('  Warning: test-result history was not available '
           'for builder \'%s\'.\n' % builder_name))
  return results_json


def _CreateTestsResultsDictionary(tr_tests_dict):
  """Create dictionary of all tests+results from the given tests dictionary.

  Parse individual tests and results from the |tr_tests_dict|, and place them
  into a flattened tests results dictionary. Most tests are standalone, and
  keyed by their test name. Some tests belong to a testinstance group, and are
  keyed by their testinstance group name, then the testinstance number
  (e.g., '0', '1', '2'), and finally the test name.

  For example, a standalone test:result is formatted thus:
  "BookmarksTest.CommandOpensBookmarksTab": {
    "results": [...]
    "times": [...]
  }

  Tests grouped under a testinstance, are formatted thus:
  "KioskUpdateSuite": {
    "KioskUpdateTest.PermissionChange": {
      "1": {
        "results": [...],
        "times": [...]
      }
    "KioskUpdateTest.PermissionChange": {
      "0": {
        "results": [...],
        "times": [...]
      }
    }

  The flattened test results dictionary is formatted thus:
    {
      BookmarksTest.CommandOpensBookmarksTab: [[60, u'Q'], [440, u'P']],
      KioskUpdateTest.PermissionChange/0: [[498, u'P'], [2, u'Q']]
      KioskUpdateTest.PermissionChange/1: [[493, u'P'], [7, u'Q']]
    }

  Args:
    tr_tests_dict: Dictionary of test groups & tests.

  Returns:
    Dictionary of flattened tests and their results.
  """
  tests_results_dict = {}
  standalone = 0
  group = 0
  subtest = 0

  for group_name in tr_tests_dict:
    test_group = tr_tests_dict[group_name]
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

  print('  Number of standalone tests: %s' % standalone)
  print('  Number of instance tests (in %s groups): %s' % (group, subtest))
  print('  Total tests results: %s\n' % len(tests_results_dict))

  return tests_results_dict


def _CreateUserTestsResults(run_user_tests, stdio_tests_dict,
                            tests_results_dict):
  """Create dictionary of tests results for all user-specified tests.

  If a user test is failed in the build status given by |stdio_tests_dict|,
  then set the test result to failed code: 'Q'. If a user test is in the test
  results given by |test_results_dict|, then use those results. Otherwise,
  use the test result given by |stdio_tests_dict|. If a user test is missing
  from both |stdio_tests_dict| and |test_results_dict|, then set the test
  test result to missing code: 'O'.

  Args:
    run_user_tests: List of run instances of user specified tests.
    stdio_tests_dict: builder's results.json test results.
    tests_results_dict: test results from the tests-results server.

  Returns:
    Dictionary of tests and results for all user specified tests.
  """
  user_tests_results_dict = {}
  # Iterate over tests in the run user-specified tests list.
  for test_name in run_user_tests:
    if (test_name in stdio_tests_dict and
        stdio_tests_dict[test_name] == [[999, u'Q']]):
      test_result = stdio_tests_dict[test_name]
    elif test_name in tests_results_dict:  # Use test-results server results.
      test_result = tests_results_dict[test_name]
    elif test_name in stdio_tests_dict:  # Use builder results.json results.
      test_result = stdio_tests_dict[test_name]
    else:
      test_result = [[999, u'O']]  # Set result to missing.
    user_tests_results_dict[test_name] = test_result
  return user_tests_results_dict


def _CreateResultOfTests(user_tests_results_dict):
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


def _ReportTestsByResult(result_of_tests_dict, tr_dict, rout, rdir):
  """Print and write report of tests, grouped by result type.

  Args:
    result_of_tests_dict: Dictionary of results for tests.
    tr_dict: Dictionary of tests to results for builder.
    rout: flag whether to write report file.
    rdir: Directory where to write report.
  """
  # Test report result types and section headers.
  report_results_headers = {
      _NOTRUN: 'Test Status: Not Run',
      _FAILED: 'Test Result: Fail or other Error',
      _PASSED: 'Test Result: Passed recently',
      _MISSING: 'Test Result: Passing long-term'
  }
  report_section_order = [_NOTRUN, _FAILED, _PASSED, _MISSING]

  if rout:
    ofile = open(rdir+'/report', 'w')
  for result_type in report_section_order:
    header = report_results_headers[result_type]
    tests = result_of_tests_dict[result_type]
    print('%s (%s)' % (header, len(tests)))
    if rout:
      ofile.write('%s (%s)\n' % (header, len(tests)))
    for num, test in enumerate(sorted(tests)):
      if test in tr_dict:
        print('  %s) %s: %s' % (num+1, test, tr_dict[test][0:2]))
        if rout:
          ofile.write('  %s) %s: %s\n' % (num+1, test, tr_dict[test]))
      else:
        print('  %s) %s' % (num+1, test))
        if rout:
          ofile.write('  %s) %s\n' % (num+1, test))
  if rout:
    ofile.close()


def _SetUrlHost(url, host):
  """Modify builder |url| to point to the the correct |host|.

  Args:
    url: Builder URL, which may not have the correct host.
    host: Correct builder host.

  Returns:
    Builder URL with the correct host.
  """
  pattern = '(?:http.?://)?(?P<host>[^:/ ]+).*'
  m = re.search(pattern, url)
  original_host = m.group('host')
  rehosted_url = re.sub(original_host, host, url)
  return rehosted_url


def main():
  """Report test results of specified browsertests."""
  parser = argparse.ArgumentParser(
      description=('Report run status and test results for a user-specified '
                   'list of browsertest tests.'),
      formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('--tests_file', dest='tests_file', default=_TESTS_FILE,
                      help=('Specify tests path/file '
                            '(default is %s).' % _TESTS_FILE))
  parser.add_argument('--report_out', dest='report_out', default=None,
                      help=('Write report (default is None).'))
  parser.add_argument('--report_dir', dest='report_dir', default=_REPORT_DIR,
                      help=('Specify path to report directory '
                            '(default is %s).' % _REPORT_DIR))
  parser.add_argument('--master', dest='master', default=_TR_MASTER,
                      help=('Specify build master repository '
                            '(default is %s).' % _TR_MASTER))
  parser.add_argument('--builder_host', dest='builder_host',
                      default=_BUILDER_HOST,
                      help=('Specify builder host name '
                            '(default is %s).' % _BUILDER_HOST))
  parser.add_argument('--builder_project', dest='builder_project',
                      default=_BUILDER_PROJECT,
                      help=('Specify builder project name '
                            '(default is %s).' % _BUILDER_PROJECT))
  parser.add_argument('--builder_name', dest='builder_name',
                      default=_BUILDER_NAME,
                      help=('Specify builder name '
                            '(default is %s).' % _BUILDER_NAME))
  parser.add_argument('--build_num', dest='build_num', type=int,
                      default=_BUILD_NUMBER,
                      help=('Specify positive build number, or negative '
                            'index from latest build '
                            '(default is %s).' % _BUILD_NUMBER))
  parser.add_argument('--test_type', dest='test_type', default=_TEST_TYPE,
                      help=('Specify test type: browser_tests or '
                            'interactive_ui_tests '
                            '(default is %s).' % _TEST_TYPE))
  parser.add_argument('--version', dest='cr_version', default=None,
                      help=('Specify chromium version number '
                            '(default is None).'))
  parser.add_argument('--print_types', dest='print_types',
                      action='store_true', help='Print test result types.')
  arguments = parser.parse_args()

  ### Set parameters from CLI arguments, and check for valid values.
  # Set parameters from command line arguments.
  tests_file = arguments.tests_file
  report_out = arguments.report_out
  report_dir = arguments.report_dir
  master = arguments.master
  builder_host = arguments.builder_host
  builder_proj = arguments.builder_project
  builder_name = arguments.builder_name
  build_num = arguments.build_num
  test_type = arguments.test_type
  cr_version = arguments.cr_version
  print_types = arguments.print_types

  # Print map of test result types and exit.
  if print_types:
    print('Test result types:')
    print(json.dumps(_RESULT_TYPES, indent=4))
    sys.exit(0)

  # Ensure default or user-defined |tests_file| points to a real file.
  if not os.path.isfile(tests_file):
    print('Error: Could not find tests file. Try passing in --tests_file.')
    sys.exit(2)

  # Ensure default or user-defined |report_dir| points to a real directory.
  if not os.path.exists(report_dir):
    print(('Error: Could not find report directory. '
           'Try passing in --report_dir.'))
    sys.exit(2)

  # Verify that user gave |build_num| or |cr_version|, but not both.
  if build_num != _BUILD_NUMBER and cr_version:
    print(('Error: You may specify the build_num or the cr_version, '
           'but not both.'))
    sys.exit(2)

  # Verify user gave valid |test_type|.
  if test_type not in ['browser_tests', 'interactive_ui_tests']:
    print(('Error: Invalid test_type: %s. Use \'browser_tests\' or '
           '\'interactive_ui_tests\'') % test_type)
    sys.exit(2)

  # Pack valid build info into a portable dictionary.
  build_dict = {
      'builder_host': builder_host,
      'builder_proj': builder_proj,
      'builder_name': builder_name,
      'build_num': build_num,
      'test_type': test_type,
      'cr_version': cr_version
  }

  ### Get list of user tests from |tests_file|.
  user_tests = _GetUserSpecifiedTests(tests_file)

  ### Determine build number from which to get status.
  # Get list of available builds from builder.
  builds_list = _GetBuildsList(build_dict)

  # Find the latest completed build by chromium version.
  if cr_version:
    build_num = _FindBuildByChromiumVersion(build_dict)

  # Set nominal build_num from builds available in |builds_list|.
  build_dict['build_num'] = _GetNominalBuildNumber(build_num, builds_list)

  # Get number of latest completed build, and update build_dict with it.
  build_num, build_test_status_dict = (
      _LatestCompletedBuild(build_dict, builds_list))
  build_dict['build_num'] = build_num

  ### Get build status from the builder for the build number.
  # Get the build status of the latest completed build.
  build_status_dict = _GetBuildStatus(build_dict)

  # Extract the build properties, and print chromium version.
  build_properties = build_status_dict['properties']
  _PrintChromiumVersion(build_properties)

  ### Get test status from the builder for the build number.
  # Get list of failed tests from build status.
  tests_failed_list = _GetTestsFailedList(build_dict, build_status_dict)

  # Get stdio log URL from build test status for the latest build_num.
  stdio_log_url = (
      _GetStdioLogUrlFromBuildStatus(build_dict, build_test_status_dict))

  # Get dictionary of test instances run on selected build.
  stdio_tests_dict = _GetStdioLogTests(stdio_log_url, tests_failed_list)

  # Get instances of run and not run user tests.
  run_user_tests, notrun_user_tests = (
      _RunAndNotrunTests(stdio_tests_dict, user_tests))

  ### Read test results from test-results server for the builder.
  test_results_json = _GetTestResultsJson(master, builder_name, test_type)
  if test_results_json:
    # Extract tests results dictionary from results json for builder.
    tr_tests_dict = json.loads(test_results_json)[builder_name]['tests']
    tests_results_dict = _CreateTestsResultsDictionary(tr_tests_dict)
  else:
    # Extract test results from stdio tests dictionary.
    tests_results_dict = stdio_tests_dict

  ### Combine run user tests, build test status, and test results into a
  ### single dictionary of user tests and their results, and then into a
  ### dictionary of results and their tests.
  # Create dictionary of run user test instances and results.
  user_tests_results_dict = (
      _CreateUserTestsResults(run_user_tests, stdio_tests_dict,
                              tests_results_dict))

  # Create dictionary of run tests that are failed, passed, and missing.
  result_of_tests_dict = _CreateResultOfTests(user_tests_results_dict)

  # Add list of not run tests to the result of tests dictionary.
  result_of_tests_dict[_NOTRUN] = notrun_user_tests

  ### Output report of tests grouped by result. Result types are notrun,
  ### failed, passed, and missing
  _ReportTestsByResult(result_of_tests_dict, tests_results_dict,
                       report_out, report_dir)

if __name__ == '__main__':
  main()
