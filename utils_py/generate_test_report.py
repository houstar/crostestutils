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
import operator
import optparse
import os
import re
import sys

try:
  from chromite.lib import cros_build_lib
except ImportError:
  # N.B., this script needs to work outside the chroot, from both
  # 'src/scripts' and from 'crostestutils/utils_py'.
  script_path = os.path.dirname(os.path.abspath(__file__))
  cros_path = os.path.join(script_path, '../../../..')
  for lib_path in (script_path, cros_path):
    chromite_path = os.path.join(lib_path, 'chromite')
    if os.path.isdir(chromite_path):
      sys.path.append(lib_path)
  from chromite.lib import cros_build_lib
from chromite.lib import terminal

_STDOUT_IS_TTY = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

class CrashWaiver:
  """Represents a crash that we want to ignore for now."""
  def __init__(self, signals, deadline, url, person):
    self.signals = signals
    self.deadline = datetime.datetime.strptime(deadline, '%Y-%b-%d')
    self.issue_url = url
    self.suppressor = person

# List of crashes which are okay to ignore. This list should almost always be
# empty. If you add an entry, include the bug URL and your name, something like
#     'crashy':CrashWaiver(
#       ['sig 11'], '2011-Aug-18', 'http://crosbug/123456', 'developer'),

_CRASH_WHITELIST = {
}


class ResultCollector(object):
  """Collects status and performance data from an autoserv results directory."""

  def __init__(self, collect_perf=True, collect_attr=False, collect_info=False,
               escape_error=False, strip_text='',
               whitelist_chrome_crashes=False):
    """Initialize ResultsCollector class.

    Args:
      collect_perf: Should perf keyvals be collected?
      collect_attr: Should attr keyvals be collected?
      collect_info: Should info keyvals be collected?
      escape_error: Escape error message text for tools.
      strip_text: Prefix to strip from test directory names.
      whitelist_chrome_crashes: Treat Chrome crashes as non-fatal.
    """
    self._collect_perf = collect_perf
    self._collect_attr = collect_attr
    self._collect_info = collect_info
    self._escape_error = escape_error
    self._strip_text = strip_text
    self._whitelist_chrome_crashes = whitelist_chrome_crashes

  def _CollectPerf(self, testdir):
    """Parses keyval file under testdir and return the perf keyval pairs."""
    if not self._collect_perf:
      return {}
    return self._CollectKeyval(testdir, 'perf')

  def _CollectAttr(self, testdir):
    """Parses keyval file under testdir and return the attr keyval pairs."""
    if not self._collect_attr:
      return {}
    return self._CollectKeyval(testdir, 'attr')

  def _CollectKeyval(self, testdir, keyword):
    """Parses keyval file under testdir.

    If testdir contains a result folder, process the keyval file and return
    a dictionary of perf keyval pairs.

    Args:
      testdir: The autoserv test result directory.
      keyword: The keyword of keyval, either 'perf' or 'attr'.

    Returns:
      If the perf option is disabled or the there's no keyval file under
      testdir, returns an empty dictionary. Otherwise, returns a dictionary of
      parsed keyvals. Duplicate keys are uniquified by their instance number.
    """
    keyval = {}
    keyval_file = os.path.join(testdir, 'results', 'keyval')
    if not os.path.isfile(keyval_file):
      return keyval

    instances = {}

    for line in open(keyval_file):
      match = re.search(r'^(.+){%s}=(.+)$' % keyword, line)
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

        keyval[key_inst] = val

    return keyval

  def _CollectCrashes(self, status_raw):
    """Parses status_raw file for crashes.

    Saves crash details if crashes are discovered.  If a whitelist is
    present, only records whitelisted crashes.

    Args:
      status_raw: The contents of the status.log or status file from the test.

    Returns:
      A list of crash entries to be reported.
    """
    crashes = []
    regex = re.compile('Received crash notification for ([-\w]+).+ (sig \d+)')
    chrome_regex = re.compile(r'^supplied_[cC]hrome|^chrome$')
    for match in regex.finditer(status_raw):
      w = _CRASH_WHITELIST.get(match.group(1))
      if self._whitelist_chrome_crashes and chrome_regex.match(match.group(1)):
        print '@@@STEP_WARNINGS@@@'
        print '%s crashed with %s' % (match.group(1), match.group(2))
      elif (w is not None and match.group(2) in w.signals and
            w.deadline > datetime.datetime.now()):
        print 'Ignoring crash in %s for waiver that expires %s' % (
            match.group(1), w.deadline.strftime('%Y-%b-%d'))
      else:
        crashes.append('%s %s' % match.groups())
    return crashes

  def _CollectInfo(self, testdir, custom_info):
    """Parses *_info files under testdir/sysinfo/var/log.

    If the sysinfo/var/log/*info files exist, save information that shows
    hw, ec and bios version info.

    This collection of extra info is disabled by default (this funtion is
    a no-op).  It is enabled only if the --info command-line option is
    explicitly supplied.  Normal job parsing does not supply this option.

    Args:
      testdir: The autoserv test result directory.
      custom_info: Dictionary to collect detailed ec/bios info.

    Returns:
      Returns a dictionary of info that was discovered.
    """
    if not self._collect_info:
      return {}
    info = custom_info

    sysinfo_dir = os.path.join(testdir, 'sysinfo', 'var', 'log')
    for info_file, info_keys in {'ec_info.txt': ['fw_version'],
                                 'bios_info.txt': ['fwid', 'hwid']}.iteritems():
      info_file_path = os.path.join(sysinfo_dir, info_file)
      if not os.path.isfile(info_file_path):
        continue
      # Some example raw text that might be matched include:
      #
      # fw_version           | snow_v1.1.332-cf20b3e
      # fwid = Google_Snow.2711.0.2012_08_06_1139 # Active firmware ID
      # hwid = DAISY TEST A-A 9382                # Hardware ID
      info_regex = re.compile(r'^(%s)\s*[|=]\s*(.*)' % '|'.join(info_keys))
      with open(info_file_path, 'r') as f:
        for line in f:
          line = line.strip()
          line = line.split('#')[0]
          match = info_regex.match(line)
          if match:
            info[match.group(1)] = str(match.group(2)).strip()
    return info

  def _MakeResultKey(self, testdir):
    """Helper to shorten directory for easier review of long printed lines.

    WITHOUT --strip [all lines exceed 80 characters]

    /tmp/run_remote_tests.MVyY/tmp.combined-control.cHThH
                               [  FAILED  ]
    /tmp/run_remote_tests.MVyY/tmp.combined-control.cHThH/firmware_SoftwareSync.
    normal                     [  PASSED  ]
    /tmp/run_remote_tests.MVyY/tmp.combined-control.cHThH/firmware_SoftwareSync.
    normal/firmware_FAFTClient [  PASSED  ]

    WITH --strip

    /tmp/run_remote_tests.MVyY/tmp.combined-control.cHThH [  FAILED  ]
    firmware_SoftwareSync.normal                          [  PASSED  ]
    firmware_SoftwareSync.normal/firmware_FAFTClient      [  PASSED  ]

    Args:
      testdir: The autoserv test result directory.

    Returns:
      If the option for shortening the directory is provided, truncates the
      long directory path for a cleaner output report.
    """
    if testdir.startswith(self._strip_text):
      return testdir.replace(self._strip_text, '', 1)
    return testdir

  def _CollectEndTimes(self, status_raw, status_re='', is_end=True):
    """Helper to match and collect timestamp and localtime.

    Preferred to locate timestamp and localtime with an 'END GOOD test_name...'
    line.  Howerver, aborted tests occasionally fail to produce this line
    and then need to scrape timestamps from the 'START test_name...' line.

    Args:
      status_raw: multi-line text to search.
      status_re: status regex to seek (e.g. GOOD|FAIL)
      is_end: if True, search for 'END' otherwise 'START'.

    Returns:
      Tuple of timestamp, localtime retrieved from the test status log.
    """
    timestamp = ''
    localtime = ''

    localtime_re = r'\w+\s+\w+\s+[:\w]+'
    match_filter = r'^\s*%s\s+(?:%s).*timestamp=(\d*).*localtime=(%s).*$' % (
        'END' if is_end else 'START', status_re, localtime_re)
    matches = re.findall(match_filter, status_raw, re.MULTILINE)
    if matches:
      # There may be multiple lines with timestamp/localtime info.
      # The last one found is selected because it will reflect the end time.
      for i in xrange(len(matches)):
        timestamp_, localtime_ = matches[-(i+1)]
        if not timestamp or timestamp_ > timestamp:
          timestamp = timestamp_
          localtime = localtime_
    return timestamp, localtime

  def _CollectResult(self, testdir, results):
    """Collects results stored under testdir into a dictionary.

    The presence/location of status files (status.log, status and
    job_report.html) varies depending on whether the job is a simple
    client test, simple server test, old-style suite or new-style
    suite.  For example:
    -In some cases a single job_report.html may exist but many times
     multiple instances are produced in a result tree.
    -Most tests will produce a status.log but client tests invoked
     by a server test will only emit a status file.

    The two common criteria that seem to define the presence of a
    valid test result are:
    1. Existence of a 'status.log' or 'status' file. Note that if both a
       'status.log' and 'status' file exist for a test, the 'status' file
       is always a subset of the 'status.log' fle contents.
    2. Presence of a 'debug' directory.

    In some cases multiple 'status.log' files will exist where the parent
    'status.log' contains the contents of multiple subdirectory 'status.log'
    files.  Parent and subdirectory 'status.log' files are always expected
    to agree on the outcome of a given test.

    The test results discovered from the 'status*' files are included
    in the result dictionary.  The test directory name and a test directory
    timestamp/localtime are saved to be used as sort keys for the results.

    Args:
      testdir: The autoserv test result directory.
      results: A list to which a populated test-result-dictionary will
               be appended if a status file is found.
    """
    status_file = os.path.join(testdir, 'status.log')
    if not os.path.isfile(status_file):
      status_file = os.path.join(testdir, 'status')
      if not os.path.isfile(status_file):
        return

    # Status is True if GOOD, else False for all others.
    status = False
    error_msg = None
    status_raw = open(status_file, 'r').read()
    failure_tags = 'ABORT|ERROR|FAIL|TEST_NA'
    warning_tag = 'WARN'
    failure = re.search(r'%s' % failure_tags, status_raw)
    warning = re.search(r'%s' % warning_tag, status_raw) and not failure
    good = (re.search(r'GOOD.+completed successfully', status_raw) and
               not (failure or warning))

    # We'd like warnings to allow the tests to pass, but still gather info.
    if good or warning:
      status = True

    if not good:
      match = re.search(r'^\t+(%s|%s)\t(.+)' % (failure_tags, warning_tag),
                        status_raw, re.MULTILINE)
      if match:
        failure_type = match.group(1)
        reason = match.group(2).split('\t')[4]
        if self._escape_error:
          reason = re.escape(reason)
        error_msg = ': '.join([failure_type, reason])

    # Grab the timestamp - it can be used for sorting the test runs.
    # Grab the localtime - it may be printed to enable line filtering by date.
    # Designed to match a line like this:
    #   END GOOD  test_name ... timestamp=1347324321  localtime=Sep 10 17:45:21
    status_re = r'GOOD|%s|%s' % (failure_tags, warning_tag)
    timestamp, localtime = self._CollectEndTimes(status_raw, status_re)
    # Hung tests will occasionally skip printing the END line so grab
    # a default timestamp from the START line in those cases.
    if not timestamp:
      timestamp, localtime = self._CollectEndTimes(status_raw, is_end=False)

    results.append({
        'testdir': self._MakeResultKey(testdir),
        'crashes': self._CollectCrashes(status_raw),
        'status': status,
        'error_msg': error_msg,
        'localtime': localtime,
        'timestamp': timestamp,
        'perf': self._CollectPerf(testdir),
        'attr': self._CollectAttr(testdir),
        'info': self._CollectInfo(testdir, {'localtime': localtime,
                                            'timestamp': timestamp})})

  def RecursivelyCollectResults(self, resdir):
    """Recursively collect results into a list of dictionaries.

    Only recurses into directories that possess a 'debug' subdirectory
    because anything else is not considered a 'test' directory.

    Args:
      resdir: results/test directory to parse results from and recurse into.

    Returns:
      List of dictionaries of results.
    """
    results = []
    self._CollectResult(resdir, results)
    for testdir in glob.glob(os.path.join(resdir, '*')):
      # Remove false positives that are missing a debug dir.
      if not os.path.exists(os.path.join(testdir, 'debug')):
        continue

      results.extend(self.RecursivelyCollectResults(testdir))
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
    self._color = terminal.Color(options.color)
    self._results = []

  def _CollectAllResults(self):
    """Parses results into the self._results list.

    Builds a list (self._results) where each entry is a dictionary of result
    data from one test (which may contain other tests). Each dictionary will
    contain values such as: test folder, status, localtime, crashes, error_msg,
    perf keyvals [optional], info [optional].
    """
    collector = ResultCollector(self._options.perf, self._options.attr,
                                self._options.info, self._options.escape_error,
                                self._options.strip,
                                self._options.whitelist_chrome_crashes)
    for resdir in self._args:
      if not os.path.isdir(resdir):
        cros_build_lib.Die('%r does not exist', resdir)
      self._results.extend(collector.RecursivelyCollectResults(resdir))

    if not self._results:
      cros_build_lib.Die('no test directories found')

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

    The test results are aligned by discovering the longest width test
    directory name or perf key stored in the list of result dictionaries.

    Returns:
      The width for the test column.
    """
    width = 0
    for result in self._results:
      width = max(width, len(result['testdir']))
      perf = result.get('perf')
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
        except IOError:
          print 'Could not open %s' % path

  def _PrintResultDictKeyVals(self, test_entry, result_dict):
    """Formatted print a dict of keyvals like 'perf' or 'info'.

    This function emits each keyval on a single line for uncompressed review.
    The 'perf' dictionary contains performance keyvals while the 'info'
    dictionary contains ec info, bios info and some test timestamps.

    Args:
      test_entry: The unique name of the test (dir) - matches other test output.
      result_dict: A dict of keyvals to be presented.
    """
    if not result_dict:
      return
    dict_keys = result_dict.keys()
    dict_keys.sort()
    width = self._GetTestColumnWidth()
    for dict_key in dict_keys:
      if self._options.csv:
        key_entry = dict_key
      else:
        key_entry = dict_key.ljust(width - self._KEYVAL_INDENT)
        key_entry = key_entry.rjust(width)
      value_entry = self._color.Color(self._color.BOLD, result_dict[dict_key])
      self._PrintEntries([test_entry, key_entry, value_entry])

  def _GetSortedTests(self):
    """Sort the test result dictionaries in preparation for results printing.

    By default sorts the results directionaries by their test names.
    However, when running long suites, it is useful to see if an early test
    has wedged the system and caused the remaining tests to abort/fail. The
    datetime-based chronological sorting allows this view.

    Uses the --sort-chron command line option to control.
    """
    if self._options.sort_chron:
      # Need to reverse sort the test dirs to ensure the suite folder shows
      # at the bottom. Because the suite folder shares its datetime with the
      # last test it shows second-to-last without the reverse sort first.
      tests = sorted(self._results, key=operator.itemgetter('testdir'),
                     reverse=True)
      tests = sorted(tests, key=operator.itemgetter('timestamp'))
    else:
      tests = sorted(self._results, key=operator.itemgetter('testdir'))
    return tests

  def _GenerateReportText(self):
    """Prints a result report to stdout.

    Prints a result table to stdout. Each row of the table contains the test
    result directory and the test result (PASS, FAIL). If the perf option is
    enabled, each test entry is followed by perf keyval entries from the test
    results.
    """
    tests = self._GetSortedTests()
    width = self._GetTestColumnWidth()

    crashes = {}
    tests_pass = 0
    self._PrintDashLine(width)

    for result in tests:
      testdir = result['testdir']
      test_entry = testdir if self._options.csv else testdir.ljust(width)

      status_entry = self._GenStatusString(result['status'])
      if result['status']:
        color = self._color.GREEN
        tests_pass += 1
      else:
        color = self._color.RED

      test_entries = [test_entry, self._color.Color(color, status_entry)]

      info = result.get('info', {})
      info.update(result.get('attr', {}))
      if self._options.csv and (self._options.info or self._options.attr):
        if info:
          test_entries.extend(['%s=%s' % (k, info[k])
                               for k in sorted(info.keys())])
        if not result['status'] and result['error_msg']:
          test_entries.append('reason="%s"' % result['error_msg'])

      self._PrintEntries(test_entries)
      self._PrintErrors(test_entry, result['error_msg'])

      # Print out error log for failed tests.
      if not result['status']:
        self._PrintErrorLogs(testdir, test_entry)

      # Emit the perf keyvals entries. There will be no entries if the
      # --no-perf option is specified.
      self._PrintResultDictKeyVals(test_entry, result['perf'])

      # Determine that there was a crash during this test.
      if result['crashes']:
        for crash in result['crashes']:
          if not crash in crashes:
            crashes[crash] = set([])
          crashes[crash].add(testdir)

      # Emit extra test metadata info on separate lines if not --csv.
      if not self._options.csv:
        self._PrintResultDictKeyVals(test_entry, info)

    self._PrintDashLine(width)

    if not self._options.csv:
      total_tests = len(tests)
      percent_pass = 100 * tests_pass / total_tests
      pass_str = '%d/%d (%d%%)' % (tests_pass, total_tests, percent_pass)
      print 'Total PASS: ' + self._color.Color(self._color.BOLD, pass_str)

    if self._options.crash_detection:
      print ''
      if crashes:
        print self._color.Color(self._color.RED,
                                'Crashes detected during testing:')
        self._PrintDashLine(width)

        for crash_name, crashed_tests in sorted(crashes.iteritems()):
          print self._color.Color(self._color.RED, crash_name)
          for crashed_test in crashed_tests:
            print self._Indent(crashed_test)

        self._PrintDashLine(width)
        print 'Total unique crashes: ' + self._color.Color(self._color.BOLD,
                                                           str(len(crashes)))

      # Sometimes the builders exit before these buffers are flushed.
      sys.stderr.flush()
      sys.stdout.flush()

  def Run(self):
    """Runs report generation."""
    self._CollectAllResults()
    self._GenerateReportText()
    for d in self._results:
      if not d['status'] or (self._options.crash_detection and d['crashes']):
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
  parser.add_option('--info', dest='info', action='store_true',
                    default=False,
                    help='Include info keyvals in the report')
  parser.add_option('--escape-error', dest='escape_error', action='store_true',
                    default=False,
                    help='Escape error message text for tools.')
  parser.add_option('--perf', dest='perf', action='store_true',
                    default=True,
                    help='Include perf keyvals in the report [default]')
  parser.add_option('--attr', dest='attr', action='store_true',
                    default=False,
                    help='Include attr keyvals in the report')
  parser.add_option('--no-perf', dest='perf', action='store_false',
                    help='Don\'t include perf keyvals in the report')
  parser.add_option('--strip', dest='strip', type='string', action='store',
                    default='results.',
                    help='Strip a prefix from test directory names'
                    ' [default: \'%default\']')
  parser.add_option('--no-strip', dest='strip', const='', action='store_const',
                    help='Don\'t strip a prefix from test directory names')
  parser.add_option('--sort-chron', dest='sort_chron', action='store_true',
                    default=False,
                    help='Sort results by datetime instead of by test name.')
  parser.add_option('--no-debug', dest='print_debug', action='store_false',
                    default=True,
                    help='Don\'t print out logs when tests fail.')
  parser.add_option('--whitelist_chrome_crashes',
                    dest='whitelist_chrome_crashes',
                    action='store_true', default=False,
                    help='Treat Chrome crashes as non-fatal.')
  (options, args) = parser.parse_args()

  if not args:
    parser.print_help()
    cros_build_lib.Die('no result directories provided')

  if options.csv and (options.print_debug or options.crash_detection):
    Warning('Forcing --no-debug --no-crash-detection')
    options.print_debug = False
    options.crash_detection = False

  generator = ReportGenerator(options, args)
  generator.Run()


if __name__ == '__main__':
  main()
