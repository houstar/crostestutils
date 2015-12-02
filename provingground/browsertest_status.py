#!/usr/bin/python2
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Script to display latest test run status for a user-specified list of
# browsertests. The names of the desired browertests are read from a file
# located (by default) in the same directory as this script.
#
# Latest test run status for a build is fetched from the builder, read from
# the 'stdio' text file located at:
#   http://BUILDER_HOST/p/BUILDER_PROJECT/builders/BUILDER_NAME/
#   builds/BUILD_NUMBER/steps/TEST_TYPE/logs/stdio/text
#

"""Script to report test status of user-specified browsertests."""

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

# Input file and report directory parameter defaults.
_TESTS_FILE = './tests'  # Path to the file that contains the tests names.
_REPORT_DIR = os.getcwd()  # Path to the directory to store the results report.

# Test result types.
_FAIL = 'Fail'
_PASS = 'Pass'

# Report header result types.
_NOTRUN = 'NotRun'
_FAILED = 'Failed'
_PASSED = 'Passed'


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
  builder_url = (
      'https://%s/p/%s/builders/%s' %
      (urllib2.quote(build_dict['builder_host']),
       urllib2.quote(build_dict['builder_proj']),
       urllib2.quote(build_dict['builder_name'])))
  builder_json_url = (
      'https://%s/p/%s/json/builders/%s' %
      (urllib2.quote(build_dict['builder_host']),
       urllib2.quote(build_dict['builder_proj']),
       urllib2.quote(build_dict['builder_name'])))

  # Fetch builder status file from builder url.
  print('\nFetching builder status file from: %s' % builder_url)
  try:
    response = urllib2.urlopen(builder_json_url)
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


def _LatestCompletedBuildByVersion(build_dict, builds_list):
  """Find latest completed build with chrome version from list of builds.

  Check each build in the |builds_list|, starting with the build number in
  the given |build_dict|, to determine if the build completed successfully.
  If completed successfully, check to see if it contains the specified
  version of Chrome. Return the number of the build. If none of the builds
  completed successfully, or contain the specified Chrome version, exit.

  Args:
    build_dict: build info dictionary, with build number and version.
    builds_list: List of cached build numbers on the builder.

  Returns:
    Build number of the latest successfully completed build that has the
    specified version of Chrome, and the build test status dictionary of
    that build.
  """
  # Find the latest completed build, starting from build_num.
  build_num = build_dict['build_num']
  requested_cr_version = build_dict['cr_version']
  requested_build_num = build_num
  requested_build_num_failed = False
  requested_build_index = builds_list.index(requested_build_num)
  build_status_dict = None
  for build_num in reversed(builds_list[0:requested_build_index+1]):
    build_test_status_dict = _BuildIsCompleted(build_dict, build_num)
    if build_test_status_dict is not None:
      # Found completed build. Check for requested cr_version.
      if requested_cr_version is not None:
        # Get build status and Chrome version of the latest completed build.
        build_status_dict = _GetBuildStatus(build_dict, build_num)
        build_properties = build_status_dict['properties']
        build_cr_version = _GetBuildProperty(build_properties,
                                             'buildspec_version')
        if build_cr_version == requested_cr_version:
          break
        else:
          continue
      break
    requested_build_num_failed = True
  else:  # loop exhausted list builds.
    print('No completed builds are available.')
    sys.exit(2)
  if requested_build_num_failed:
    print('Error: Requested build %s was not completed successfully.' %
          requested_build_num)

  # Get Chrome OS and Chrome versions from the latest completed build.
  if build_status_dict is None:
    build_status_dict = _GetBuildStatus(build_dict, build_num)
  build_properties = build_status_dict['properties']
  build_cros_branch = _GetBuildProperty(build_properties, 'branch')
  build_cr_version = _GetBuildProperty(build_properties, 'buildspec_version')

  print('Using latest successfully completed build:')
  print('  Build Number: %s' % build_num)
  print('  Chrome OS Version: %s' % build_cros_branch)
  print('  Chrome Version: %s\n' % build_cr_version)
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
  build_url = (
      'https://%s/p/%s/builders/%s/builds/%s' %
      (urllib2.quote(build_dict['builder_host']),
       urllib2.quote(build_dict['builder_proj']),
       urllib2.quote(build_dict['builder_name']),
       build_dict['build_num']))
  build_json_url = (
      'https://%s/p/%s/json/builders/%s/builds?select=%s/steps/%s/' %
      (urllib2.quote(build_dict['builder_host']),
       urllib2.quote(build_dict['builder_proj']),
       urllib2.quote(build_dict['builder_name']),
       build_dict['build_num'],
       urllib2.quote(build_dict['test_type'])))
  print('Fetching build test status file from builder: %s' % build_url)
  return _FetchStatusFromUrl(build_dict, build_json_url)


def _GetBuildStatus(build_dict, build_num=None):
  """Get the build status for the given build number.

  Fetch the build status file from the builder for the given |build_num|.
  If nominal |build_num| is not given, default to that stored in build_dict.

  Args:
    build_dict: Build info dictionary.
    build_num: Nominal build number.

  Returns:
    Build Status dictionary.
  """
  if build_num is None:
    build_num = build_dict['build_num']

  # Generate percent-encoded build status url.
  build_url = (
      'https://%s/p/%s/builders/%s/builds/%s' %
      (urllib2.quote(build_dict['builder_host']),
       urllib2.quote(build_dict['builder_proj']),
       urllib2.quote(build_dict['builder_name']),
       build_num))
  build_url_json = (
      'https://%s/p/%s/json/builders/%s/builds/%s' %
      (urllib2.quote(build_dict['builder_host']),
       urllib2.quote(build_dict['builder_proj']),
       urllib2.quote(build_dict['builder_name']),
       build_num))
  print('Fetching build status file from builder: %s' % build_url)
  return _FetchStatusFromUrl(build_dict, build_url_json)


def _FetchStatusFromUrl(build_dict, build_url_json):
  """Get the status from the given URL.

  Args:
    build_dict: Build info dictionary.
    build_url_json: URL to the status json file.

  Returns:
    Status dictionary.
  """
  # Fetch json status file from build url.
  hosted_url = _SetUrlHost(build_url_json, build_dict['builder_host'])
  url = urllib2.urlopen(hosted_url)
  status_file = url.read()
  url.close()

  # Convert json status file to status dictionary and return.
  return json.loads(status_file)


def _GetBuildProperty(build_properties, property_name):
  """Get the specified build property from the build properties dictionary.

  Example property names are Chromium OS Version ('branch'), Chromium OS
  Version ('buildspec_version'), and GIT Revision ('git_revision').

  Args:
    build_properties: The properties dictionary for the build.
    property_name: The name of the build property.

  Returns:
    A string containing the property value.
  """
  for property_list in build_properties:
    if property_name in property_list:
      property_value = property_list[1]
      break
  else:
    property_value = None
    print('  Warning: Build properties has no %s property.' % property_name)
  return property_value


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
      break  # Exit step_dict loop if test_type is in text_list.
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

    If a test is in the |tests_failed_list|, then set the test result to
    'Fail'. Otherwise, set result to 'Pass'.

    Here is the format of the dictionary:
    {
      MaybeSetMetadata/SafeBrowseService.MalwareImg/1: 'Pass',
      MaybeSetMetadata/SafeBrowseService.MalwareImg/2: 'Fail',
      PlatformAppBrowserTest.ComponentBackgroundPage: 'Pass',
      NoSessionRestoreTest.LocalStorageClearedOnExit: 'Pass']
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
        test_result = _FAIL  # Test Result Failed.
      else:
        test_result = _PASS  # Test Result Passed.
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


def _CreateUserTestsResults(run_user_tests, stdio_tests_dict):
  """Create dictionary of tests results for all user-specified tests.

  If a user test is in the build status given by |stdio_tests_dict|, then
  use the test result stored in |stdio_tests_dict|. Otherwise, set the test
  test result to 'Missing'.

  Args:
    run_user_tests: List of run instances of user specified tests.
    stdio_tests_dict: builder's results.json test results.

  Returns:
    Dictionary of tests and results for all user specified tests.
  """
  user_tests_results_dict = {}
  # Iterate over tests in the run user-specified tests list.
  for test_name in run_user_tests:
    if test_name in stdio_tests_dict:  # Use result from builder results.json.
      test_result = stdio_tests_dict[test_name]
    else:
      test_result = 'Missing'  # Set result to missing.
    user_tests_results_dict[test_name] = test_result
  return user_tests_results_dict


def _CreateResultOfTests(user_tests_results_dict):
  """Create dictionary of user tests keyed by result.

  Args:
    user_tests_results_dict: dictionary of user tests to results.

  Returns:
    Dictionary of results of tests.
  """
  failed_tests = []
  passed_tests = []
  for test in user_tests_results_dict:
    result = user_tests_results_dict[test]
    if result == _PASS:
      passed_tests.append(test)
    elif result == _FAIL:
      failed_tests.append(test)
  return {_FAILED: failed_tests, _PASSED: passed_tests}


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
      _NOTRUN: 'Test Status: Missing',
      _FAILED: 'Test Result: Failed or other Error',
      _PASSED: 'Test Result: Passed'
  }
  report_section_order = [_NOTRUN, _FAILED, _PASSED]

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
        print('  %s) %s' % (num+1, test))
        if rout:
          ofile.write('  %s) %s\n' % (num+1, test))
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
  arguments = parser.parse_args()

  ### Set parameters from CLI arguments, and check for valid values.
  # Set parameters from command line arguments.
  tests_file = arguments.tests_file
  report_out = arguments.report_out
  report_dir = arguments.report_dir
  builder_host = arguments.builder_host
  builder_proj = arguments.builder_project
  builder_name = arguments.builder_name
  build_num = arguments.build_num
  test_type = arguments.test_type
  cr_version = arguments.cr_version

  # Ensure default or user-defined |tests_file| points to a real file.
  if not os.path.isfile(tests_file):
    print('Error: Could not find tests file. Try passing in --tests_file.')
    sys.exit(2)

  # Ensure default or user-defined |report_dir| points to a real directory.
  if not os.path.exists(report_dir):
    print(('Error: Could not find report directory. '
           'Try passing in --report_dir.'))
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

  # Set nominal build_num from builds available in |builds_list|.
  build_dict['build_num'] = _GetNominalBuildNumber(build_num, builds_list)

  # Get number of latest completed build, and update build_dict with it.
  build_num, build_test_status_dict = (
      _LatestCompletedBuildByVersion(build_dict, builds_list))
  build_dict['build_num'] = build_num
  build_status_dict = _GetBuildStatus(build_dict)

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

  ### Combine run user tests and build test status into a single dictionary
  ### of user tests and their results, and then into a dictionary of results
  ### and their tests.
  # Create dictionary of run user test instances and results.
  user_tests_results_dict = (
      _CreateUserTestsResults(run_user_tests, stdio_tests_dict))

  # Create dictionary of run tests that are failed, passed, and missing.
  result_of_tests_dict = _CreateResultOfTests(user_tests_results_dict)

  # Add list of not run tests to the result of tests dictionary.
  result_of_tests_dict[_NOTRUN] = notrun_user_tests

  ### Output report of tests grouped by result. Result types are notrun,
  ### failed, passed, and missing
  _ReportTestsByResult(result_of_tests_dict, stdio_tests_dict,
                       report_out, report_dir)

if __name__ == '__main__':
  main()
