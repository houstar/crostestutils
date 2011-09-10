# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing methods and classes to interact with a devserver instance.
"""

import os
import threading
import time

import cros_build_lib as cros_lib
import update_exception

# Wait up to 3 minutes for the dev server to start.
DEV_SERVER_TIMEOUT = 180

def GenerateUpdateId(target, src, key):
  """Returns a simple representation id of target and src paths."""
  update_id = target
  if src: update_id = '->'.join([src, update_id])
  if key: update_id = '+'.join([update_id, key])
  return update_id

class DevServerWrapper(threading.Thread):
  """A Simple wrapper around a dev server instance."""

  def __init__(self, test_root):
    self.proc = None
    self.test_root = test_root
    self._log_filename = os.path.join(test_root, 'dev_server.log')
    threading.Thread.__init__(self)

  def run(self):
    # Kill previous running instance of devserver if it exists.
    cros_lib.RunCommand(['sudo', 'pkill', '-f', 'devserver.py'], error_ok=True,
                        print_cmd=False)
    cros_lib.RunCommand(['sudo',
                         'start_devserver',
                         '--archive_dir=./static',
                         '--client_prefix=ChromeOSUpdateEngine',
                         '--production',
                         ], enter_chroot=True, print_cmd=False,
                         log_to_file=self._log_filename,
                         cwd=cros_lib.GetCrosUtilsPath())

  def Stop(self):
    """Kills the devserver instance."""
    cros_lib.RunCommand(['sudo', 'pkill', '-f', 'devserver.py'], error_ok=True,
                        print_cmd=False)

  def PrintLog(self):
    """Print devserver output."""
    # Open in update mode in case the child process hasn't opened the file yet.
    log = open(self._log_filename, 'w+')
    print '--- Start output from %s ---' % self._log_filename
    for line in log:
      sys.stdout.write(line)
    print '--- End output from %s ---' % self._log_filename
    log.close()

  def WaitUntilStarted(self):
    """Wait until the devserver has started."""
    # Open in update mode in case the child process hasn't opened the file yet.
    log = open(self._log_filename, 'w+')
    pos = 0
    for _ in range(DEV_SERVER_TIMEOUT * 2):
      log.seek(pos)
      for line in log:
        # When the dev server has started, it will print a line stating
        # 'Bus STARTED'. Wait for that line to appear.
        if 'Bus STARTED' in line:
          log.close()
          return
        # If we've read a complete line, and it doesn't contain the magic
        # phrase, move on to the next line.
        if line.endswith('\n'):
          pos = log.tell()
      # Looks like it hasn't started yet. Keep waiting...
      time.sleep(0.5)
    else:
      log.close()
      self.PrintLog()
      error = 'Timeout waiting for devserver startup.'
      raise update_exception.UpdateException(1, error)

  @classmethod
  def GetDevServerURL(cls, port, sub_dir):
    """Returns the dev server url for a given port and sub directory."""
    ip_addr = cros_lib.GetIPAddress()
    if not port: port = 8080
    url = 'http://%(ip)s:%(port)s/%(dir)s' % {'ip': ip_addr,
                                              'port': str(port),
                                              'dir': sub_dir}
    return url
