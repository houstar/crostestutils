# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing implementation of an au_worker for virtual machines."""

import os

import cros_build_lib as cros_lib

from crostestutils.au_test_harness import au_worker


class VMAUWorker(au_worker.AUWorker):
  """Test harness for updating virtual machines."""

  def __init__(self, options, test_results_root):
    """Processes vm-specific options."""
    super(VMAUWorker, self).__init__(options, test_results_root)
    self.graphics_flag = ''
    if options.no_graphics: self.graphics_flag = '--no_graphics'
    if not self.board: cros_lib.Die('Need board to convert base image to vm.')

  def _KillExistingVM(self, pid_file):
    """Kills an existing VM specified by the pid_file."""
    if os.path.exists(pid_file):
      cros_lib.RunCommand(['./cros_stop_vm', '--kvm_pid=%s' % pid_file],
                          cwd=self.crosutilsbin, print_cmd=False,
                          error_ok=True)

    assert not os.path.exists(pid_file)

  def CleanUp(self):
    """Stop the vm after a test."""
    self._KillExistingVM(self._kvm_pid_file)

  def PrepareBase(self, image_path, signed_base=False):
    """Creates an update-able VM based on base image."""
    self.PrepareVMBase(image_path, signed_base)

  def UpdateImage(self, image_path, src_image_path='', stateful_change='old',
                  proxy_port='', private_key_path=None):
    """Updates VM image with image_path."""
    log_directory = self.GetNextResultsPath('update')
    stateful_change_flag = self.GetStatefulChangeFlag(stateful_change)
    if src_image_path and self._first_update:
      src_image_path = self.vm_image_path
      self._first_update = False

    cmd = ['%s/cros_run_vm_update' % self.crosutilsbin,
           '--vm_image_path=%s' % self.vm_image_path,
           '--update_log=%s' % os.path.join(log_directory, 'update_engine.log'),
           '--snapshot',
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
    self.RunUpdateCmd(cmd, log_directory)

  def UpdateUsingPayload(self, update_path, stateful_change='old',
                         proxy_port=None):
    """Updates a vm image using cros_run_vm_update."""
    log_directory = self.GetNextResultsPath('update')
    stateful_change_flag = self.GetStatefulChangeFlag(stateful_change)
    cmd = ['%s/cros_run_vm_update' % self.crosutilsbin,
           '--payload=%s' % update_path,
           '--vm_image_path=%s' % self.vm_image_path,
           '--update_log=%s' % os.path.join(log_directory, 'update_engine.log'),
           '--snapshot',
           self.graphics_flag,
           '--persist',
           '--kvm_pid=%s' % self._kvm_pid_file,
           '--ssh_port=%s' % self._ssh_port,
           stateful_change_flag,
          ]
    if proxy_port: cmd.append('--proxy_port=%s' % proxy_port)
    self.TestInfo(self.GetUpdateMessage(update_path, None, True, proxy_port))
    self.RunUpdateCmd(cmd, log_directory)

  def VerifyImage(self, unittest, percent_required_to_pass=100, test=''):
    """Runs vm smoke suite or any single test to verify image."""
    log_directory = self.GetNextResultsPath('verify')
    (_, _, log_directory_in_chroot) = log_directory.rpartition('chroot')
    # image_to_live already verifies lsb-release matching.  This is just
    # for additional steps.
    if not test: test = self.verify_suite

    command = ['./cros_run_vm_test',
               '--image_path=%s' % self.vm_image_path,
               '--snapshot',
               '--persist',
               '--kvm_pid=%s' % self._kvm_pid_file,
               '--ssh_port=%s' % self._ssh_port,
               '--results_dir_root=%s' % log_directory_in_chroot,
               test,
              ]
    if self.graphics_flag: command.append(self.graphics_flag)
    self.TestInfo('Running smoke suite to verify image.')
    output = cros_lib.RunCommand(
        command, error_ok=(percent_required_to_pass != 100),
        enter_chroot=False, redirect_stdout=True, redirect_stderr=True,
        cwd=self.crosutilsbin, print_cmd=False, combine_stdout_stderr=True)
    return self.AssertEnoughTestsPassed(unittest, output,
                                        percent_required_to_pass)
