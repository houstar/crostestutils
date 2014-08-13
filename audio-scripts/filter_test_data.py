#!/usr/bin/python
#
# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''Filter test data.

Test results without rms perf data are filtered out.
Test specific filter logic could also be added into filter_test.
'''

import argparse
import re
import sys
import utils


RE_FORMAT_CONVERSION_RMS = re.compile(r'rms_value_\d+_\d+')


def average(numbers):
  total = 0
  count = 0
  for v in numbers:
    total += v
    count += 1
  return total / count


def filter_test(test):
  if len(test.perf_dict) == 0:
    return None
  if test.test_name == 'audio_CRASFormatConversion':
    value = average(float(v) for k, v in test.perf_dict.iteritems()
                    if RE_FORMAT_CONVERSION_RMS.match(k))
    test.perf_dict = {'average_rms_value': value}
  return test


def parse_arguments():
  parser = argparse.ArgumentParser(description='Filter the test data.')
  parser.add_argument(
      'input', type=argparse.FileType('r'), nargs='?', default=sys.stdin,
      help='input file, a list of tests\' tags. (default stdin)')
  parser.add_argument(
      '--output', '-o', type=argparse.FileType('w'), nargs='?',
      default=sys.stdout, help='the output file. (default stdout)')
  return parser.parse_args()


def main():
  args = parse_arguments()
  for line in args.input:
    test = utils.TestObject.parse(line)
    if test is not None:
      test = filter_test(test)
    if test is not None:
      args.output.write('%s\n' % str(test))


if __name__ == '__main__':
  main()
