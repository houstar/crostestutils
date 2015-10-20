#!/usr/bin/python2
#
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for gce_au_worker."""

from __future__ import print_function

import mock
import os
import sys
import unittest

import constants
sys.path.append(constants.CROS_PLATFORM_ROOT)
sys.path.append(constants.SOURCE_ROOT)

from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import parallel
from chromite.lib import path_util
from chromite.lib import portage_util
from crostestutils.au_test_harness.au_worker import AUWorker
from crostestutils.au_test_harness.gce_au_worker import GCEAUWorker
from crostestutils.lib.gce import GceContext


class Options(object):
  """A fake class to hold command line options."""

  def __init__(self):
    self.board = 'lakitu'
    self.delta = False
    self.verbose = False
    self.quick_test = False
    self.verify_suite_name = 'gce-smoke'


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
    osutils.Touch(options.ssh_private_key)
    self.options = options

    test_results_root = os.path.join(self.tempdir, 'test-results')
    self.test_results_all = os.path.join(test_results_root, 'all')
    self.test_results_failed = os.path.join(test_results_root, 'failed')
    osutils.SafeMakedirs(self.test_results_all)
    self.test_results_root = test_results_root

    self.json_key_file = os.path.join(self.tempdir, 'service_account.json')
    osutils.Touch(self.json_key_file)

    self.image_path = os.path.join(self.tempdir, self.GCE_TARBALL)
    osutils.Touch(self.image_path)

    # Mock out model or class level methods.
    self.PatchObject(AUWorker, 'GetNextResultsPath', autospec=True,
                     return_value=(self.test_results_all,
                                   self.test_results_failed))
    self.PatchObject(GceContext, 'ForServiceAccountThreadSafe',
                     spec=GceContext.ForServiceAccountThreadSafe)

  def testUpdateImageWithoutCustomTests(self):
    """Tests UpdateImage's behavior when no custom tests are specified.

    This test verifies that when no custom gce_tests.json is found, the
    gce-smoke suite will be used as verification test and no special flags will
    be used at instance creation time.
    """
    # Fake an empty gce_tests.json.
    self.PatchObject(portage_util, 'ReadOverlayFile', autospec=True,
                     return_value=None)

    # Initialize GCEAUWorker. gce_tests.json will be loaded.
    worker = GCEAUWorker(self.options, self.test_results_root,
                         project=self.PROJECT, zone=self.ZONE,
                         network=self.NETWORK, gcs_bucket=self.BUCKET,
                         json_key_file=self.json_key_file)

    # There are no custom tests specified. The gce-smoke suite will be run, and
    # no special flags will be used at instance creation.
    self.assertListEqual([dict(name="suite:gce-smoke", flags=dict())],
                         worker.tests)

    # Call UpdateImage.
    self.PatchObject(worker.gce_context, 'CreateInstance', autospec=True)
    self.PatchObject(worker, '_CreateImage', autospec=True)
    worker.UpdateImage(self.image_path)

    # Verify that only one instance is created and no additional kwargs are
    # passed to CreateInstance.
    worker.gce_context.CreateInstance.assert_called_once_with(
        mock.ANY, mock.ANY, mock.ANY, network=self.NETWORK, zone=self.ZONE)

  def testUpdateImageWithCustomTests(self):
    """Tests UpdateImage's behavior with custom tests.

    This tests verifies that when a custom gce_tests.json is provided, tests
    specified in it will be used to verify the image, and instances will be
    created for each test target as specificed, with specificed GCE flags.
    """
    # Fake gce_tests.json.
    tests_json = """
    {
        "tests": [
            {
              "name": "suite:suite1",
              "flags": {
                  "foo": "bar"
              }
            },
            {
              "name": "suite:suite2",
              "flags": {
                  "bar": "foo"
              }
            },
            {
              "name": "foo_test",
              "flags": {}
            }
        ]
    }
    """
    self.PatchObject(portage_util, 'ReadOverlayFile', autospec=True,
                     return_value=tests_json)

    # Initialize GCEAUWorker. It should load gce_tests.json.
    worker = GCEAUWorker(self.options, self.test_results_root,
                         project=self.PROJECT, zone=self.ZONE,
                         network=self.NETWORK, gcs_bucket=self.BUCKET,
                         json_key_file=self.json_key_file)

    # Assert that tests specificed in gce_tests.json are loaded and will be run
    # later to verify the image.
    self.assertSetEqual(
        set([test['name'] for test in worker.tests]),
        set(['suite:suite1', 'suite:suite2', 'foo_test'])
    )

    # UpdateImage is expected to create instances for each test with correct
    # flags.
    self.PatchObject(worker.gce_context, 'CreateInstance', autospec=True)
    self.PatchObject(worker, '_CreateImage', autospec=True)
    worker.UpdateImage(self.image_path)

    # Assert that instances are created for each test.
    self.assertSetEqual(
        set(worker.instances.keys()),
        set(['suite:suite1', 'suite:suite2', 'foo_test'])
    )

    # Assert that correct flags are applied.
    worker.gce_context.CreateInstance.assert_called_with(
        mock.ANY, mock.ANY, mock.ANY, network=self.NETWORK, zone=self.ZONE,
        foo='bar')
    worker.gce_context.CreateInstance.assert_called_with(
        mock.ANY, mock.ANY, mock.ANY, network=self.NETWORK, zone=self.ZONE,
        bar='foo')
    worker.gce_context.CreateInstance.assert_called_with(
        mock.ANY, mock.ANY, mock.ANY, network=self.NETWORK, zone=self.ZONE)

  def testVerifyImage(self):
    """Verifies that VerifyImage runs required tests on correct instances."""
    worker = GCEAUWorker(self.options, self.test_results_root,
                         project=self.PROJECT, zone=self.ZONE,
                         network=self.NETWORK, gcs_bucket=self.BUCKET,
                         json_key_file=self.json_key_file)
    # Fake tests and instances.
    worker.tests = [
        dict(name='suite:suite1', flags=dict(foo='bar')),
        dict(name='suite:suite2', flags=dict(bar='foo')),
        dict(name='foo_test', flags=dict()),
    ]
    worker.instances = {
        'suite:suite1': 'instance_1',
        'suite:suite2': 'instance_2',
        'foo_test': 'instance_3',
    }

    expected_tests_run = [
        dict(remote='1.1.1.1', test='suite:suite1'),
        dict(remote='2.2.2.2', test='suite:suite2'),
        dict(remote='3.3.3.3', test='foo_test'),
    ]
    actual_tests_run = []

    def _OverrideGetInstanceIP(instance, *unused_args, **unused_kwargs):
      if instance == 'instance_1':
        return '1.1.1.1'
      elif instance == 'instance_2':
        return '2.2.2.2'
      else:
        return '3.3.3.3'

    def _OverrideRunCommand(cmd, *unused_args, **unused_kwargs):
      remote = cmd[-3]
      test = cmd[-2]
      actual_tests_run.append(dict(remote=remote, test=test))
      return cros_build_lib.CommandResult()

    def _OverrideRunParallelSteps(steps, *unused_args, **unused_kwargs):
      """Run steps sequentially."""
      return_values = []
      for step in steps:
        ret = step()
        return_values.append(ret)
      return return_values

    self.PatchObject(worker.gce_context, 'CreateInstance', autospec=True)
    self.PatchObject(path_util, 'ToChrootPath', autospec=True,
                     return_value='x/y/z')
    self.PatchObject(worker.gce_context, 'GetInstanceIP',
                     autospec=True,
                     side_effect=_OverrideGetInstanceIP)
    self.PatchObject(cros_build_lib, 'RunCommand',
                     autospec=True,
                     side_effect=_OverrideRunCommand)
    self.PatchObject(AUWorker, 'ParseGeneratedTestOutput', autospec=True,
                     return_value=100)
    self.PatchObject(parallel, 'RunParallelSteps', autospec=True,
                     side_effect=_OverrideRunParallelSteps)

    # VerifyImage should run all expected tests.
    worker.VerifyImage(None)

    # Assert that expected and only expected tests are run.
    self.assertEqual(len(expected_tests_run), len(actual_tests_run))
    for test in expected_tests_run:
      self.assertIn(test, actual_tests_run)

  def testCleanUp(self):
    """Tests that CleanUp deletes all instances and doesn't leak processes."""
    worker = GCEAUWorker(self.options, self.test_results_root,
                         project=self.PROJECT, zone=self.ZONE,
                         network=self.NETWORK, gcs_bucket=self.BUCKET,
                         json_key_file=self.json_key_file)
    for cmd in ['CopyInto', 'DoCommand']:
      self.PatchObject(worker.gscontext, cmd, autospec=True)

    self.PatchObject(worker.gce_context, 'DeleteInstance', autospec=True)

    for _ in range(3):
      worker.UpdateImage(self.image_path)
    self.assertEqual(len(worker.bg_delete_processes), 2)

    worker.CleanUp()
    self.assertEqual(len(worker.bg_delete_processes), 0)

  def testHandleFail(self):
    """Tests that _HandleFail copies necessary files for repro."""
    worker = GCEAUWorker(self.options, self.test_results_root,
                         project=self.PROJECT, zone=self.ZONE,
                         network=self.NETWORK, gcs_bucket=self.BUCKET,
                         json_key_file=self.json_key_file)
    for cmd in ['CopyInto', 'DoCommand']:
      self.PatchObject(worker.gscontext, cmd, autospec=True)
    self.PatchObject(cros_build_lib, 'RunCommand', autospec=True)
    self.PatchObject(worker, '_DeleteInstancesIfExist', autospec=True)
    self.PatchObject(path_util, 'ToChrootPath', autospec=True,
                     return_value='x/y/z')
    self.PatchObject(worker, '_RunTest', autospec=True,
                     return_value=(0, None, None))
    worker.UpdateImage(self.image_path)
    worker.VerifyImage(None)
    self.assertExists(os.path.join(self.test_results_failed, self.GCE_TARBALL))
    self.assertExists(os.path.join(
        self.test_results_failed,
        os.path.basename(self.options.ssh_private_key)))


if __name__ == '__main__':
  unittest.main()
