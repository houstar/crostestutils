# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing methods and classes to interact with a devserver instance.
"""

import os
import multiprocessing
import re
import sys
import time

import constants
from chromite.lib import cros_build_lib

# Wait up to 15 minutes for the dev server to start. It can take a while to
# start when generating payloads in parallel.
DEV_SERVER_TIMEOUT = 900


def GetIPAddress(device='eth0'):
  """Returns the IP Address for a given device using ifconfig.

  socket.gethostname() is insufficient for machines where the host files are
  not set up "correctly."  Since some of our builders may have this issue,
  this method gives you a generic way to get the address so you are reachable
  either via a VM or remote machine on the same network.
  """
  result = cros_build_lib.RunCommandCaptureOutput(
      ['/sbin/ifconfig', device], print_cmd=False)
  match = re.search('.*inet addr:(\d+\.\d+\.\d+\.\d+).*', result.output)
  if match:
    return match.group(1)
  cros_build_lib.Warning('Failed to find ip address in %r', result.output)
  return None


def GenerateUpdateId(target, src, key, for_vm):
  """Returns a simple representation id of target and src paths."""
  update_id = target
  if src: update_id = '->'.join([src, update_id])
  if key: update_id = '+'.join([update_id, key])
  if not for_vm: update_id = '+'.join([update_id, 'patched_kernel'])
  return update_id


class DevServerException(Exception):
  """Thrown when the devserver fails to start up correctly."""


class DevServerWrapper(multiprocessing.Process):
  """A Simple wrapper around a dev server instance."""

  def __init__(self, test_root):
    self.proc = None
    self.test_root = test_root
    self._log_filename = os.path.join(test_root, 'dev_server.log')
    multiprocessing.Process.__init__(self)

  def run(self):
    # Kill previous running instance of devserver if it exists.
    self.Stop()
    cmd = ['start_devserver', '--archive_dir=./static', '--production']
    cros_build_lib.SudoRunCommand(cmd, enter_chroot=True, print_cmd=False,
                                  log_stdout_to_file=self._log_filename,
                                  combine_stdout_stderr=True,
                                  cwd=constants.SOURCE_ROOT)

  def Stop(self):
    """Kills the devserver instance if it exists."""
    cros_build_lib.SudoRunCommand(['pkill', '-f', 'devserver.py'],
                                  error_code_ok=True, print_cmd=False)

  def PrintLog(self):
    """Print devserver output."""
    print '--- Start output from %s ---' % self._log_filename
    # Open in update mode in case the child process hasn't opened the file yet.
    with open(self._log_filename) as log:
      sys.stdout.writelines(log)
    print '--- End output from %s ---' % self._log_filename

  def WaitUntilStarted(self):
    """Wait until the devserver has started."""
    # Open in update mode in case the child process hasn't opened the file yet.
    pos = 0
    with open(self._log_filename, 'w+') as log:
      for _ in range(DEV_SERVER_TIMEOUT * 2):
        log.seek(pos)
        for line in log:
          # When the dev server has started, it will print a line stating
          # 'Bus STARTED'. Wait for that line to appear.
          if 'Bus STARTED' in line:
            return
          # If we've read a complete line, and it doesn't contain the magic
          # phrase, move on to the next line.
          if line.endswith('\n'):
            pos = log.tell()
        # Looks like it hasn't started yet. Keep waiting...
        time.sleep(0.5)
    self.PrintLog()
    raise DevServerException('Timeout waiting for the devserver to startup.')

  @classmethod
  def GetDevServerURL(cls, port=None, sub_dir=None):
    """Returns the dev server url for a given port and sub directory."""
    if not port: port = 8080
    url = 'http://%(ip)s:%(port)s' % {'ip': GetIPAddress(), 'port': str(port)}
    if sub_dir:
      url += '/' + sub_dir

    return url

  @classmethod
  def WipePayloadCache(cls):
    """Cleans up devserver cache of payloads."""
    cros_build_lib.Info('Cleaning up previously generated payloads.')
    cmd = ['start_devserver', '--clear_cache', '--exit']
    cros_build_lib.SudoRunCommand(
        cmd, enter_chroot=True, print_cmd=False, combine_stdout_stderr=True,
        redirect_stdout=True, redirect_stderr=True, cwd=constants.SOURCE_ROOT)
