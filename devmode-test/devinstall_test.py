#!/usr/bin/python
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Integration test to test the basic functionality of dev-install and gmerge.

This module contains a test that runs some sanity integration tests against
a VM. First it starts a VM test image and turns it into a base image by wiping
all of the stateful partition. Once done, runs dev_install to restore the
stateful partition and then runs gmerge.
"""

import getpass
import logging
import optparse
import os
import shutil
import socket
import sys
import tempfile

import constants
sys.path.append(constants.SOURCE_ROOT)
sys.path.append(constants.CROS_PLATFORM_ROOT)

from chromite.lib import cros_build_lib
from chromite.lib import remote_access
from crostestutils.lib import dev_server_wrapper
from crostestutils.lib import mount_helper
from crostestutils.lib import test_helper


_LOCALHOST = 'localhost'
_PRIVATE_KEY = os.path.join(constants.CROSUTILS_DIR, 'mod_for_test_scripts',
                            'ssh_keys', 'testing_rsa')
_MAX_SSH_ATTEMPTS = 3

class TestError(Exception):
  """Raised on any error during testing. It being raised is a test failure."""


class DevModeTest(object):
  """Wrapper for dev mode tests."""
  def __init__(self, image_path, board, binhost):
    """
    Args:
      image_path: Filesystem path to the image to test.
      board: Board of the image under test.
      binhost: Binhost override. Binhost as defined here is where dev-install
               or gmerge go to search for binary packages. By default this will
               be set to the devserver url of the host running this script.
               If no override i.e. the default is ok, set to None.
    """
    self.image_path = image_path
    self.board = board
    self.binhost = binhost

    self.tmpdir = tempfile.mkdtemp('DevModeTest')
    self.tmpkvmpid = os.path.join(self.tmpdir, 'kvm_pid')

    self.working_image_path = None
    self.devserver = None
    self.remote_access = None
    self.port = None

  def Cleanup(self):
    """Clean up any state at the end of the test."""
    try:
      if self.working_image_path:
        os.remove(self.working_image_path)

      if self.devserver:
        self.devserver.Stop()

      self.devserver = None
      self._StopVM()

      if self.tmpdir:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

      self.tmpdir = None
    except Exception:
      logging.warning('Received error during cleanup', exc_info=True)

  def _SetupSSH(self):
    """Sets up the necessary items for running ssh."""
    self.port = self._FindUnusedPort()
    self.remote_access = remote_access.RemoteAccess(
        _LOCALHOST, self.tmpdir, self.port,
        debug_level=logging.DEBUG, interactive=False)

  def _WipeDevInstall(self):
    """Wipes the devinstall state."""
    r_mount_point = os.path.join(self.tmpdir, 'm')
    s_mount_point = os.path.join(self.tmpdir, 's')
    dev_image_path = os.path.join(s_mount_point, 'dev_image')
    mount_helper.MountImage(self.working_image_path,
                            r_mount_point, s_mount_point, read_only=False,
                            safe=True)
    try:
      cros_build_lib.SudoRunCommand(['chown', '--recursive', getpass.getuser(),
                                     s_mount_point], debug_level=logging.DEBUG)
      shutil.rmtree(dev_image_path)
    finally:
      mount_helper.UnmountImage(r_mount_point, s_mount_point)

  def _FindUnusedPort(self):
    """Returns a currently unused port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((_LOCALHOST, 0))
    port = s.getsockname()[1]
    s.close()
    return port

  def _RobustlyStartVMWithSSH(self):
    """Start test copy of VM and ensure we can ssh into it.

    This command is more robust than just naively starting the VM as it will
    try to start the VM multiple times if the VM fails to start up. This is
    inspired by retry_until_ssh in crosutils/lib/cros_vm_lib.sh.
    """
    for _ in range(_MAX_SSH_ATTEMPTS):
      try:
        cmd = ['%s/bin/cros_start_vm' % constants.CROSUTILS_DIR,
               '--ssh_port', str(self.port),
               '--image_path', self.working_image_path,
               '--no_graphics',
               '--kvm_pid', self.tmpkvmpid]
        cros_build_lib.RunCommand(cmd, debug_level=logging.DEBUG)

        # Ping the VM to ensure we can SSH into it.
        self.remote_access.RemoteSh(['true'])
        return
      except cros_build_lib.RunCommandError as e:
        logging.warning('Failed to connect to VM')
        logging.debug(e)
        self._StopVM()
    else:
      raise TestError('Max attempts to connect to VM exceeded')

  def _StopVM(self):
    """Stops a running VM set up using _RobustlyStartVMWithSSH."""
    cmd = ['%s/bin/cros_stop_vm' % constants.CROSUTILS_DIR,
           '--kvm_pid', self.tmpkvmpid]
    cros_build_lib.RunCommand(cmd, debug_level=logging.DEBUG)

  def PrepareTest(self):
    """Pre-test modification to the image and env to setup test."""
    logging.info('Setting up the image %s for vm testing.',
                 self.image_path)
    self._SetupSSH()
    vm_path = test_helper.CreateVMImage(self.image_path, self.board,
                                        full=False)

    logging.info('Making copy of the vm image %s to manipulate.', vm_path)
    self.working_image_path = os.path.join(self.tmpdir,
                                           os.path.basename(vm_path))
    shutil.copyfile(vm_path, self.working_image_path)
    logging.debug('Copy of vm image stored at %s.', self.working_image_path)

    logging.info('Wiping /usr/local/bin from the image.')
    self._WipeDevInstall()

    logging.info('Starting the vm on port %d.', self.port)
    self._RobustlyStartVMWithSSH()

    if not self.binhost:
      logging.info('Starting the devserver.')
      self.devserver = dev_server_wrapper.DevServerWrapper(self.tmpdir)
      self.devserver.start()
      self.devserver.WaitUntilStarted()
      self.binhost = dev_server_wrapper.DevServerWrapper.GetDevServerURL(
          sub_dir='static/pkgroot/%s/packages' % self.board)

    logging.info('Using binhost %s', self.binhost)

  def TestDevInstall(self):
    """Tests that we can run dev-install and have python work afterwards."""
    try:
      logging.info('Running dev install in the vm.')
      self.remote_access.RemoteSh(
          ['bash', '-l', '-c',
           '"/usr/bin/dev_install --yes --binhost %s"' % self.binhost])

      logging.info('Verifying that python works on the image.')
      self.remote_access.RemoteSh(
          ['sudo', '-u', 'chronos', '--',
           'python', '-c', '"print \'hello world\'"'])
    except cros_build_lib.RunCommandError as e:
      self.devserver.PrintLog()
      logging.error('dev-install test failed. See devserver log above for more '
                    'details.')
      raise TestError('dev-install test failed with: %s' % str(e))

  def TestGmerge(self):
    """Evaluates whether the test passed or failed."""
    logging.info('Testing that gmerge works on the image after dev install.')
    try:
      self.remote_access.RemoteSh(
          ['gmerge', 'gmerge', '--accept_stable', '--usepkg',
           '--devserver_url', self.devserver.GetDevServerURL(),
           '--board', self.board])
    except cros_build_lib.RunCommandError as e:
      logging.error('gmerge test failed. See log for details')
      raise TestError('gmerge test failed with: %s' % str(e))


def main():
  usage = ('%s <board> <path_to_[test|vm]_image>. '
           'See --help for more options' % os.path.basename(sys.argv[0]))
  parser = optparse.OptionParser(usage)
  parser.add_option('--binhost', metavar='URL',
                    help='binhost override. By default, starts up a devserver '
                         'and uses it as the binhost.')
  parser.add_option('-v', '--verbose', default=False, action='store_true',
                    help='Print out added debugging information')

  (options, args) = parser.parse_args()

  if len(args) != 2:
    parser.print_usage()
    parser.error('Need board and path to test image.')

  board = args[0]
  image_path = os.path.realpath(args[1])

  test_helper.SetupCommonLoggingFormat(verbose=options.verbose)

  test = DevModeTest(image_path, board, options.binhost)
  try:
    test.PrepareTest()
    test.TestDevInstall()
    test.TestGmerge()
    logging.info('All tests passed.')
  finally:
    test.Cleanup()


if __name__ == '__main__':
  main()
