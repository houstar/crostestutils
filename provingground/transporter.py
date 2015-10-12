#!/usr/bin/python3
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Transporter copies log files to GS storage.

Must be a member of "chromiumos-test-logs-ninja" group or will get
"Access Denied" error from gsutil.

"""

from __future__ import print_function
import argparse
import os

def main():
  gs_path = {'broadcom':'gs://chromeos-partner-broadcom-wifi-bucket/',
             'bugs':'gs://chromiumos-test-logs/',
             'imgtech':'gs://chromeos-partner-imgtech-wifi-bucket/',
             'intel':'gs://chromeos-partner-intel-wifi-bucket/',
             'marvell':'gs://chromeos-partner-marvell-wifi-bucket/'}

  usage_desc = ('Please make sure you are part of chromiumos-test-logs-ninja '
                'group. Ping rohitbm/krisr to get yourself added to the group.')
  parser = argparse.ArgumentParser(description=usage_desc)
  parser.add_argument('-t', '--tracker', dest='tracker',
                      help='[crosp|cr|misc] bug\'s tracker name.')
  parser.add_argument('-b', '--bug', dest='bug_id',
                      help='Bug number for which the logs belong.')
  parser.add_argument('-p', '--path', dest='logs_path',
                      help='Logs local path.')
  parser.add_argument('--broadcom', action='store_true', default=False,
                      dest='broadcom',
                      help='Store logs in the Broadcom storage.')
  parser.add_argument('--imgtech', action='store_true', default=False,
                      dest='imgtech', help='Store logs in the Imgtech storage.')
  parser.add_argument('--intel', action='store_true', default=False,
                      dest='intel', help='Store logs in the Intel storage.')
  parser.add_argument('--marvell', action='store_true', default=False,
                      dest='marvell', help='Store logs in the Marvell storage.')

  arguments = parser.parse_args()

  if [arguments.broadcom, arguments.imgtech,
      arguments.intel, arguments.marvell].count(True) > 1:
    print('Error: logs can be uploaded only for one partner.')
    return 1

  if arguments.broadcom:
    final_gs_path = gs_path['broadcom']
  elif arguments.imgtech:
    final_gs_path = gs_path['imgtech']
  elif arguments.intel:
    final_gs_path = gs_path['intel']
  elif arguments.marvell:
    final_gs_path = gs_path['marvell']
  else:
    trackers = ['crosp', 'cr', 'misc']
    if arguments.tracker not in trackers:
      print('Error: invalid tracker name. Select %s' % trackers)
      return 1
    if not os.path.exists(arguments.logs_path):
      print('Error: logs file %s is not available.' % arguments.logs_path)
      return 1
    logs_dir = arguments.tracker + '_' + arguments.bug_id
    final_gs_path = gs_path['bugs'] + logs_dir + '/'

  gsutilPath = os.popen('which gsutil').read().rstrip()
  if not gsutilPath:
    print('Error: gsutil not found.')
    return 1
  file_name = os.path.basename(arguments.logs_path)
  if os.path.isfile(arguments.logs_path):
    os.popen('%s cp \'%s\' %s%s' %
             (gsutilPath, arguments.logs_path,
              final_gs_path, file_name))
  elif os.path.isdir(arguments.logs_path):
    os.popen('%s cp -R \'%s\' %s' %
             (gsutilPath, arguments.logs_path, final_gs_path))
  else:
    print('%s is neither a file nor a directory.' % arguments.logs_path)
    return 1
  link = 'https://storage.cloud.google.com/' + final_gs_path[5:]
  print('Logs link: %s%s' %
        (link, os.path.basename(arguments.logs_path)))

if __name__ == '__main__':
  main()
