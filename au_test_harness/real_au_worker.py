# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing class that implements an au_worker for a test device."""

import constants
from chromite.lib import cros_build_lib
from crostestutils.au_test_harness import au_worker


class RealAUWorker(au_worker.AUWorker):
  """Test harness for updating real images."""

  def __init__(self, options, test_results_root):
    """Processes non-vm-specific options."""
    super(RealAUWorker, self).__init__(options, test_results_root)
    self.remote = options.remote
    if not self.remote:
      cros_build_lib.Die('We require a remote address for tests.')

  def PrepareBase(self, image_path, signed_base=False):
    """Auto-update to base image to prepare for test."""
    self.PrepareRealBase(image_path, signed_base)

  def UpdateImage(self, image_path, src_image_path='', stateful_change='old',
                  proxy_port=None, private_key_path=None):
    """Updates a remote image using image_to_live.sh."""
    stateful_change_flag = self.GetStatefulChangeFlag(stateful_change)
    cmd = ['%s/image_to_live.sh' % constants.CROSUTILS_DIR,
           '--remote=%s' % self.remote,
           stateful_change_flag,
           '--verify',
          ]
    self.AppendUpdateFlags(cmd, image_path, src_image_path, proxy_port,
                           private_key_path)
    self.RunUpdateCmd(cmd)

  def UpdateUsingPayload(self, update_path, stateful_change='old',
                         proxy_port=None):
    """Updates a remote image using image_to_live.sh."""
    stateful_change_flag = self.GetStatefulChangeFlag(stateful_change)
    cmd = ['%s/image_to_live.sh' % constants.CROSUTILS_DIR,
           '--payload=%s' % update_path,
           '--remote=%s' % self.remote,
           stateful_change_flag,
           '--verify',
          ]
    if proxy_port: cmd.append('--proxy_port=%s' % proxy_port)
    self.RunUpdateCmd(cmd)

  def VerifyImage(self, unittest, percent_required_to_pass=100, test=''):
    """Verifies an image using run_remote_tests.sh with verification suite."""
    test_directory, _ = self.GetNextResultsPath('autotest_tests')
    if not test: test = self.verify_suite

    result = cros_build_lib.RunCommand(
        ['run_remote_tests.sh',
         '--remote=%s' % self.remote,
         '--results_dir_root=%s' % test_directory,
         test,
        ], error_code_ok=True, enter_chroot=True, redirect_stdout=True,
        cwd=constants.CROSUTILS_DIR)
    return self.AssertEnoughTestsPassed(unittest, result.output,
                                        percent_required_to_pass)

