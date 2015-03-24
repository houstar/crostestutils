# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing implementation of an au_worker for virtual machines."""

import os
import shutil
import tempfile

import constants
from chromite.cbuildbot import constants as buildbot_constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_logging as logging
from crostestutils.au_test_harness import au_worker
from crostestutils.au_test_harness import update_exception


class VMAUWorker(au_worker.AUWorker):
  """Test harness for updating virtual machines."""

  def __init__(self, options, test_results_root):
    """Processes vm-specific options."""
    super(VMAUWorker, self).__init__(options, test_results_root)
    self.graphics_flag = ''
    if options.no_graphics: self.graphics_flag = '--no_graphics'
    if not self.board:
      cros_build_lib.Die('Need board to convert base image to vm.')
    self.whitelist_chrome_crashes = options.whitelist_chrome_crashes

  def _KillExistingVM(self, pid_file, save_mem_path=None):
    """Kills an existing VM specified by the pid_file."""
    if not os.path.exists(pid_file):
      return

    cmd = ['./bin/cros_stop_vm', '--kvm_pid=%s' % pid_file]
    if save_mem_path is not None:
      cmd.append('--mem_path=%s' % save_mem_path)

    cros_build_lib.RunCommand(cmd, print_cmd=False, error_code_ok=True,
                              cwd=constants.CROSUTILS_DIR)

  def CleanUp(self):
    """Stop the vm after a test."""
    self._KillExistingVM(self._kvm_pid_file)

  def PrepareBase(self, image_path, signed_base=False):
    """Creates an update-able VM based on base image."""
    original_image_path = self.PrepareVMBase(image_path, signed_base)
    # This worker may be running in parallel with other VMAUWorkers, as
    # well as the archive stage of cbuildbot. Make a private copy of
    # the VM image, to avoid any conflict.
    _, private_image_path = tempfile.mkstemp(
        prefix="%s." % buildbot_constants.VM_DISK_PREFIX)
    shutil.copy(self.vm_image_path, private_image_path)
    self.TestInfo('Copied shared disk image %s to %s.' %
                  (self.vm_image_path, private_image_path))
    self.vm_image_path = private_image_path
    # Although we will run the VM with |private_image_path|, we return
    # |original_image_path|, because our return value is used to find the
    # update files. And the update files are shared across the tests
    # that share the original image.
    return original_image_path

  def _HandleFail(self, log_directory, fail_directory):
    parent_dir = os.path.dirname(fail_directory)
    if not os.path.isdir(parent_dir):
      os.makedirs(parent_dir)

    # Copy logs. Must be done before moving image, as this creates
    # |fail_directory|.
    try:
      shutil.copytree(log_directory, fail_directory)
    except shutil.Error as e:
      logging.warning('Ignoring errors while copying logs: %s', e)

    # Copy VM state. This includes the disk image, and the memory
    # image.
    try:
      _, mem_image_path = tempfile.mkstemp(
          dir=fail_directory, prefix="%s." % buildbot_constants.VM_MEM_PREFIX)
      self._KillExistingVM(self._kvm_pid_file, save_mem_path=mem_image_path)
      shutil.move(self.vm_image_path, fail_directory)
    except shutil.Error as e:
      logging.warning('Ignoring errors while copying VM files: %s', e)

  def UpdateImage(self, image_path, src_image_path='', stateful_change='old',
                  proxy_port='', private_key_path=None):
    """Updates VM image with image_path."""
    log_directory, fail_directory = self.GetNextResultsPath('update')
    stateful_change_flag = self.GetStatefulChangeFlag(stateful_change)
    cmd = ['%s/bin/cros_run_vm_update' % constants.CROSUTILS_DIR,
           '--vm_image_path=%s' % self.vm_image_path,
           '--update_log=%s' % os.path.join(log_directory, 'update_engine.log'),
           self.graphics_flag,
           '--persist',
           '--kvm_pid=%s' % self._kvm_pid_file,
           '--ssh_port=%s' % self._ssh_port,
           stateful_change_flag,
          ]
    self.AppendUpdateFlags(cmd, image_path, src_image_path, proxy_port,
                           private_key_path)
    self.TestInfo(self.GetUpdateMessage(image_path, src_image_path, True,
                                        proxy_port))
    try:
      self.RunUpdateCmd(cmd, log_directory)
    except update_exception.UpdateException:
      self._HandleFail(log_directory, fail_directory)
      raise

  def UpdateUsingPayload(self, update_path, stateful_change='old',
                         proxy_port=None):
    """Updates a vm image using cros_run_vm_update."""
    log_directory, fail_directory = self.GetNextResultsPath('update')
    stateful_change_flag = self.GetStatefulChangeFlag(stateful_change)
    cmd = ['%s/bin/cros_run_vm_update' % constants.CROSUTILS_DIR,
           '--payload=%s' % update_path,
           '--vm_image_path=%s' % self.vm_image_path,
           '--update_log=%s' % os.path.join(log_directory, 'update_engine.log'),
           self.graphics_flag,
           '--persist',
           '--kvm_pid=%s' % self._kvm_pid_file,
           '--ssh_port=%s' % self._ssh_port,
           stateful_change_flag,
          ]
    if proxy_port: cmd.append('--proxy_port=%s' % proxy_port)
    self.TestInfo(self.GetUpdateMessage(update_path, None, True, proxy_port))
    try:
      self.RunUpdateCmd(cmd, log_directory)
    except update_exception.UpdateException:
      self._HandleFail(log_directory, fail_directory)
      raise

  def AppendUpdateFlags(self, cmd, image_path, src_image_path, proxy_port,
                        private_key_path, for_vm=False):
    """Appends common args to an update cmd defined by an array.

    Calls super function with for_vm set to True.

    Args:
      See AppendUpdateFlags for description of args.
    """
    super(VMAUWorker, self).AppendUpdateFlags(
        cmd, image_path, src_image_path, proxy_port, private_key_path,
        for_vm=True)

  # pylint: disable-msg=W0221
  def VerifyImage(self, test=''):
    """Runs vm smoke suite or any single test to verify image.

    Returns True upon success.  Prints test output and returns False otherwise.
    """
    log_directory, fail_directory = self.GetNextResultsPath('autotest_tests')
    (_, _, log_directory_in_chroot) = log_directory.rpartition('chroot')
    # image_to_live already verifies lsb-release matching.  This is just
    # for additional steps.
    if not test: test = self.verify_suite

    command = ['./bin/cros_run_vm_test',
               '--board=%s' % self.board,
               '--image_path=%s' % self.vm_image_path,
               '--persist',
               '--kvm_pid=%s' % self._kvm_pid_file,
               '--ssh_port=%s' % self._ssh_port,
               '--results_dir_root=%s' % log_directory_in_chroot,
               '--verbose=0',
               test,
              ]
    if self.graphics_flag: command.append(self.graphics_flag)
    if self.whitelist_chrome_crashes:
      command.append('--whitelist_chrome_crashes')
    self.TestInfo('Running smoke suite to verify image.')
    result = cros_build_lib.RunCommand(
        command, print_cmd=False, combine_stdout_stderr=True,
        cwd=constants.CROSUTILS_DIR, error_code_ok=True,
        capture_output=True)

    # If the command failed or printed warnings, print the output.
    if result.returncode != 0 or '@@@STEP_WARNINGS@@@' in result.output:
      print result.output
      self._HandleFail(log_directory, fail_directory)

    return result.returncode == 0
