#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This module runs at system startup on Chromium OS test images. It runs through
# a set of hooks to keep a DUT from being bricked without manual intervention.
# Example hook:
#   Check to see if ethernet is connected. If its not, unload and reload the
#     ethernet driver.

import logging
import os
import subprocess
import time

LOGGING_SUBDIR = '/var/log/recover_duts'
LOG_FILENAME_FORMAT = os.path.join(LOGGING_SUBDIR,
                                   'recover_duts_log_%Y%m%d_%H%M%S.txt')
LOGGING_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
LONG_REBOOT_DELAY = 300
SLEEP_DELAY = 600


def main():
  if not os.path.isdir(LOGGING_SUBDIR):
    os.makedirs(LOGGING_SUBDIR)

  log_filename = time.strftime(LOG_FILENAME_FORMAT)
  logging.basicConfig(filename=log_filename, level=logging.DEBUG,
                      format=LOGGING_FORMAT)
  hooks_dir = os.path.join(os.path.dirname(__file__), 'hooks')

  # Additional sleep as networking not be up in the case of a long reboot.
  time.sleep(LONG_REBOOT_DELAY)
  try:
    while(True):
      for script in os.listdir(hooks_dir):
        script = os.path.join(hooks_dir, script)
        if os.path.isfile(script) and script.endswith('.hook'):
          logging.debug('Running hook: %s', script)
          popen = subprocess.Popen([script], stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
          output = popen.communicate()[0]
          if popen.returncode == 0:
            logging.debug('Running of %s succeeded with output:\n%s', script,
                          output)
          else:
            logging.warn('Running of %s failed with output:\n%s', script,
                         output)
      else:
        time.sleep(SLEEP_DELAY)

  except Exception as e:
    # Since this is run from an upstart job we want to ensure we log this into
    # our log file before dying.
    logging.fatal(str(e))
    raise


if __name__ == '__main__':
  main()
