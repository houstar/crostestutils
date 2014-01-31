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
import sys
import tempfile

import constants
sys.path.append(constants.SOURCE_ROOT)
sys.path.append(constants.CROS_PLATFORM_ROOT)

from chromite.lib import cros_build_lib
from chromite.lib import dev_server_wrapper
from chromite.lib import osutils
from chromite.lib import remote_access
from chromite.lib import vm

from crostestutils.lib import mount_helper
from crostestutils.lib import test_helper


class TestError(Exception):
  """Raised on any error during testing. It being raised is a test failure."""


class DevModeTest(object):
  """Wrapper for dev mode tests."""
  def __init__(self, image_path, board, binhost):
    """Initializes DevModeTest.

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
    self.working_image_path = None
    self.devserver = None
    self.vm = None
    self.device = None

  def Cleanup(self):
    """Cleans up any state at the end of the test."""
    try:
      if self.devserver:
        self.devserver.Stop()

      self.devserver = None
      self.device.Cleanup()
      self.vm.Stop()
      self.vm = None
      osutils.RmDir(self.tmpdir, ignore_missing=True)
      self.tmpdir = None
    except Exception:
      logging.warning('Received error during cleanup', exc_info=True)

  def _WipeDevInstall(self):
    """Wipes the devinstall state."""
    r_mount_point = os.path.join(self.tmpdir, 'm')
    s_mount_point = os.path.join(self.tmpdir, 's')
    dev_image_path = os.path.join(s_mount_point, 'dev_image')
    mount_helper.MountImage(self.working_image_path,
                            r_mount_point, s_mount_point, read_only=False,
                            safe=True)
    try:
      osutils.RmDir(dev_image_path, sudo=True)
    finally:
      mount_helper.UnmountImage(r_mount_point, s_mount_point)

  def PrepareTest(self):
    """Pre-test modification to the image and env to setup test."""
    logging.info('Setting up the image %s for vm testing.', self.image_path)
    vm_path = vm.CreateVMImage(image=self.image_path, board=self.board,
                               full=False)

    logging.info('Making copy of the vm image %s to manipulate.', vm_path)
    self.working_image_path = os.path.join(self.tmpdir,
                                           os.path.basename(vm_path))
    shutil.copyfile(vm_path, self.working_image_path)
    logging.debug('Copy of vm image stored at %s.', self.working_image_path)

    logging.info('Wiping /usr/local/bin from the image.')
    self._WipeDevInstall()

    self.vm = vm.VMInstance(self.working_image_path, tempdir=self.tmpdir)
    logging.info('Starting the vm on port %d.', self.vm.port)
    self.vm.Start()

    self.device = remote_access.ChromiumOSDevice(
        remote_access.LOCALHOST, port=self.vm.port, work_dir=self.tmpdir)

    if not self.binhost:
      logging.info('Starting the devserver.')
      self.devserver = dev_server_wrapper.DevServerWrapper()
      self.devserver.Start()
      self.binhost = dev_server_wrapper.DevServerWrapper.GetDevServerURL(
          sub_dir='static/pkgroot/%s/packages' % self.board)

    logging.info('Using binhost %s', self.binhost)

  def TestDevInstall(self):
    """Tests that we can run dev-install and have python work afterwards."""
    try:
      logging.info('Running dev install in the vm.')
      self.device.RunCommand(
          ['bash', '-l', '-c',
           '"/usr/bin/dev_install --yes --binhost %s"' % self.binhost])

      logging.info('Verifying that python works on the image.')
      self.device.RunCommand(['sudo', '-u', 'chronos', '--', 'python', '-c',
                              '"print \'hello world\'"'])
    except (cros_build_lib.RunCommandError,
            remote_access.SSHConnectionError) as e:
      self.devserver.PrintLog()
      logging.error('dev-install test failed. See devserver log above for more '
                    'details.')
      raise TestError('dev-install test failed with: %s' % str(e))

  def TestGmerge(self):
    """Evaluates whether the test passed or failed."""
    logging.info('Testing that gmerge works on the image after dev install.')
    try:
      self.device.RunCommand(
          ['gmerge', 'gmerge', '--accept_stable', '--usepkg',
           '--devserver_url', self.devserver.GetDevServerURL(),
           '--board', self.board])
    except (cros_build_lib.RunCommandError,
            remote_access.SSHConnectionError) as e:
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
