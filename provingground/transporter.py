#!/usr/bin/python
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Transporter copies logs file to GS storage.

import argparse
import os

def main():
  gs_path = 'gs://chromiumos-test-logs/'
  parser = argparse.ArgumentParser()
  parser.add_argument('-t', '--tracker', dest='tracker',
                      help='[crosp|cr|misc] bug\'s tracker name.')
  parser.add_argument('-b', '--bug', dest='bug_id',
                      help='Bug number for which the logs belong.')
  parser.add_argument('-p', '--path', dest='logs_path',
                      help='Logs local path.')
  arguments = parser.parse_args()

  trackers = ['crosp', 'cr', 'misc']
  if arguments.tracker not in trackers:
    print('Error: invalid tracker name. Select %s' % trackers)
    return 1
  if not os.path.exists(arguments.logs_path):
    print('Error: logs file %s is not available.' % arguments.logs_path)
    return 1
  logs_dir = arguments.tracker + '_' + arguments.bug_id
  gsutilPath = os.popen('which gsutil').read().rstrip()
  if not gsutilPath:
    print('Error: gsutil not found.')
    return 1
  file_name = os.path.basename(arguments.logs_path)
  if os.path.isfile(arguments.logs_path):
    os.popen('%s cp \'%s\' %s%s/%s' %
             (gsutilPath, arguments.logs_path, gs_path, logs_dir, file_name))
  elif os.path.isdir(arguments.logs_path):
    os.popen('%s cp -R \'%s\' %s%s/' %
             (gsutilPath, arguments.logs_path, gs_path, logs_dir))
  else:
    print('%s is neither a file nor a directory.' % arguments.logs_path)
    return 1
  link='https://storage.cloud.google.com/chromiumos-test-logs/'
  print('Logs link: %s%s/%s' %
        (link, logs_dir, os.path.basename(arguments.logs_path)))

if __name__ == '__main__':
  main()
