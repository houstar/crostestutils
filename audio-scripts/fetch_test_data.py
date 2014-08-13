#!/usr/bin/python
#
# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''Fetch autotest results and parse perf data for further analysis.

We need to download job tag names from cautotest for this script to download
test data. Here is how we fetch the data for recent audio tests.

Open http://cautotest/new_tko/#tab_id=spreadsheet_view

Use the following query:

test_name in (
  'audio_AlsaLoopback',
  'audio_CrasLoopback')
AND platform not in ('mario')
AND test_started_time > '2014-08-01'

Choose "Job tag" as Rows and "Status" as Columns.

Download the result as CSV file by clicking on "Export to CSV".
'''

import argparse
import logging
import re
import sys
import threading
import utils


# Regexp for matching test job tag.
RE_TEST_TAG = re.compile('\d+-chromeos-test/[\w-]+')

# Regexp for matching label keyval from test output. Example label format:
#   butterfly-release/R34-5120.0.0/audio/audiovideo_LineOutToMicInLoopback
RE_LABEL = re.compile('([\w-]+)-\w+/R(\d+)-(\d+\.\d+\.\d+)/\w+/(\w+)')

# Regexp for matching perf data from test output.
RE_PERF_KEYVAL = re.compile('(.+){perf}=(.*)')

# Lock used to prevent output messages get interlaced.
_output_lock = threading.Lock()


def test_tag_iter(input_file):
  for line in input_file:
    m = RE_TEST_TAG.search(line)
    if m is not None:
      yield m.group(0)


def parse_keyval(content):
  keyval = {}
  for line in content.splitlines():
    key, value = line.split('=', 1)
    keyval[key.strip()] = value.strip()
  return keyval


def parse_test_info_keyval(test):
  # Get information from label keyval.
  label = parse_keyval(utils.autotest_cat(test.tag, 'keyval'))['label']
  match = RE_LABEL.match(label)
  if match is None:
    raise RuntimeError('failed to parse label: %s' % label)
  test.platform, test.release, test.build, test.test_name = match.groups()


def parse_perf_result_keyval(test):
  try:
    content = utils.autotest_cat(test.tag, '%s/results/keyval' % test.test_name)
  except IOError:  # File not found on autotest GS storage.
    return

  for line in content.splitlines():
    m = RE_PERF_KEYVAL.match(line)
    if m is not None:
      test.perf_dict[m.group(1)] = m.group(2)


def fetch_and_print_test(tag, output):
  try:
    test = utils.TestObject(tag)
    parse_test_info_keyval(test)
    parse_perf_result_keyval(test)
    with _output_lock:
      output.write('%s\n' % str(test))
  except Exception:
    # Log the exception and continue.
    logging.exception('failed to extract data: %s', tag)


def parse_arguments():
  parser = argparse.ArgumentParser(
      description='Fetch the test results of specified tests.')
  parser.add_argument(
      'input', type=argparse.FileType('r'), nargs='?', default=sys.stdin,
      help='input file, a list of tests\' tags. (default stdin)')
  parser.add_argument(
      '--jobs', '-j', type=int, nargs='?', default=32,
      help='tests to fetch simultaneously (default 32)')
  parser.add_argument(
      '--output', '-o', type=argparse.FileType('w'), nargs='?',
      default=sys.stdout, help='the output file. (default stdout)')
  return parser.parse_args()


def main():
  args = parse_arguments()
  job_iter = (lambda: fetch_and_print_test(t, args.output)
              for t in test_tag_iter(args.input))

  utils.run_in_pool(job_iter, pool_size=args.jobs)


if __name__ == '__main__':
  main()
