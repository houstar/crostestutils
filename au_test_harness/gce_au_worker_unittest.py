#!/usr/bin/python2
#
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for gce_au_worker."""

from __future__ import print_function

import os
import sys
import unittest

import constants
sys.path.append(constants.CROS_PLATFORM_ROOT)
sys.path.append(constants.SOURCE_ROOT)

from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import path_util
from crostestutils.au_test_harness.gce_au_worker import GCEAUWorker
from crostestutils.lib.gce import GceContext

class Options(object):
  """A fake class to hold command line options."""

  def __init__(self):
    self.board = 'fake-board'
    self.delta = False
    self.verbose = False
    self.quick_test = False
    self.verify_suite_name = 'smoke'


class GceAuWorkerTest(cros_test_lib.MockTempDirTestCase):
  """Test suite for GCEAUWorker."""

  PROJECT = 'test-project'
  ZONE = 'test-zone'
  NETWORK = 'default'
  BUCKET = 'foo-bucket'
  CLIENT_EMAIL = 'test-account@testdomain.com'
  GCE_TARBALL = 'chromiumos_test_image_gce_tar.gz'

  def setUp(self):
    # Fake out environment.
    options = Options()
    options.ssh_private_key = os.path.join(self.tempdir, 'ssh-private-key')
    self.ssh_private_key = options.ssh_private_key
    osutils.Touch(self.ssh_private_key)

    test_results_root = os.path.join(self.tempdir, 'test-results')
    self.test_results_all = os.path.join(test_results_root, 'all')
    self.test_results_failed = os.path.join(test_results_root, 'failed')
    osutils.SafeMakedirs(self.test_results_all)

    self.json_key_file = os.path.join(self.tempdir, 'service_account.json')
    osutils.Touch(self.json_key_file)

    self.image_path = os.path.join(self.tempdir, self.GCE_TARBALL)
    osutils.Touch(self.image_path)

    self.PatchObject(GceContext, 'ForServiceAccount', autospec=True)
    self.worker = GCEAUWorker(options, test_results_root, project=self.PROJECT,
                              zone=self.ZONE, network=self.NETWORK,
                              gcs_bucket=self.BUCKET,
                              json_key_file=self.json_key_file)

    # Mock out methods.
    for cmd in ['CreateInstance', 'CreateImage', 'GetInstanceIP',
                'DeleteInstance', 'DeleteImage', 'ListInstances', 'ListImages']:
      self.PatchObject(self.worker.gce_context, cmd, autospec=True)

    for cmd in ['CopyInto', 'DoCommand']:
      self.PatchObject(self.worker.gscontext, cmd, autospec=True)

    self.PatchObject(self.worker, 'GetNextResultsPath', autospec=True,
                     return_value=(self.test_results_all,
                                   self.test_results_failed))

  def testUpdateImage(self):
    """Tests that UpdateImage creates a GCE VM using the given tarball."""

    def _CopyInto(src, _):
      self.assertEqual(self.image_path, src)

    self.PatchObject(self.worker.gscontext, 'CopyInto', autospec=True,
                     side_effect=_CopyInto)
    self.PatchObject(self.worker, '_DeleteInstanceIfExists', autospec=True)
    self.PatchObject(self.worker, 'GetNextResultsPath', autospec=True,
                     return_value=('test-resultsi-all', 'test-results-failed'))
    self.worker.UpdateImage(self.image_path)

    #pylint: disable=protected-access
    self.worker._DeleteInstanceIfExists.assert_called_once_with()
    #pylint: enable=protected-access
    self.assertNotEqual(self.worker.instance, '')
    self.assertNotEqual(self.worker.image, '')
    self.assertTrue(self.worker.gscontext.CopyInto.called)

  def testCleanUp(self):
    """Tests that CleanUp deletes all instances and doesn't leak processes."""
    for _ in range(3):
      self.worker.UpdateImage(self.image_path)
    self.assertEqual(len(self.worker.bg_delete_processes), 2)

    self.worker.CleanUp()
    self.assertEqual(len(self.worker.bg_delete_processes), 0)

  def testVerifyImage(self):
    """Tests that VerifyImage calls out to test_that with correct args."""

    def _RunCommand(cmd, *args, **kwargs):
      expected_cmd = ['test_that', '-b', 'fake-board', '--no-quickmerge',
                      '--results_dir=%s' % self.test_results_all, '1.2.3.4',
                      'suite:smoke']
      for i, arg in enumerate(expected_cmd):
        self.assertEqual(arg, cmd[i])

      return cros_build_lib.CommandResult()

    self.PatchObject(cros_build_lib, 'RunCommand', autospec=True,
                     side_effect=_RunCommand)
    self.PatchObject(self.worker, 'AssertEnoughTestsPassed', autospec=True)
    self.PatchObject(self.worker, '_DeleteInstanceIfExists', autospec=True)
    self.PatchObject(self.worker.gce_context, 'GetInstanceIP', autospec=True,
                     return_value='1.2.3.4')
    self.PatchObject(path_util, 'ToChrootPath', autospec=True,
                     return_value='x/y/z')
    self.worker.UpdateImage(self.image_path)
    self.worker.VerifyImage(None)
    self.assertTrue(cros_build_lib.RunCommand.called)

  def testHandleFail(self):
    """Tests that _HandleFail copies necessary files for repro."""
    self.PatchObject(cros_build_lib, 'RunCommand', autospec=True)
    self.PatchObject(self.worker, '_DeleteInstanceIfExists', autospec=True)
    self.PatchObject(path_util, 'ToChrootPath', autospec=True,
                     return_value='x/y/z')
    self.PatchObject(self.worker, 'AssertEnoughTestsPassed', autospec=True,
                     return_value=False)
    self.worker.UpdateImage(self.image_path)
    self.worker.VerifyImage(None)
    self.assertExists(os.path.join(self.test_results_failed, self.GCE_TARBALL))
    self.assertExists(os.path.join(self.test_results_failed,
                                   os.path.basename(self.ssh_private_key)))


if __name__ == '__main__':
  unittest.main()
