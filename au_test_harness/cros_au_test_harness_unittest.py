#!/usr/bin/python2
#
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests module containing unittests for cros_au_test_harness.py.

Instead of calling to functions/methods in cros_au_test_harness, tests defined
here use its binary version, to mimic the behavior of ctest.
"""

from __future__ import print_function

import os
import sys
import unittest
import uuid

import constants
sys.path.append(constants.SOURCE_ROOT)

from chromite.lib import cros_build_lib


class CrosAuTestHarnessTest(unittest.TestCase):
  """Testing the GCE related funcionalities in cros_au_test_harness.py"""

  INVALID_TYPE_ERROR = 'Failed to specify valid test type.'
  INVALID_IMAGE_PATH = 'Testing requires a valid target image.'

  def testCheckOptionsDisallowsUndefinedType(self):
    """Verifies that CheckOptions complains about invalid type."""
    cmd = [os.path.join(constants.CROSUTILS_DIR, 'bin', 'cros_au_test_harness'),
           '--type=aws'
          ]
    with self.assertRaises(cros_build_lib.RunCommandError) as cm:
      cros_build_lib.RunCommand(cmd)

    self.assertIn(self.INVALID_TYPE_ERROR, cm.exception.result.error)

  def testCheckOptionsRecognizesGceType(self):
    """Verifies that 'gce' is an allowed type."""
    cmd = [os.path.join(constants.CROSUTILS_DIR, 'bin', 'cros_au_test_harness'),
           '--type=gce'
          ]
    # We don't have all required flags passed in so still expect an exception,
    # but it won't be complaining about invalid type.
    with self.assertRaises(cros_build_lib.RunCommandError) as cm:
      cros_build_lib.RunCommand(cmd)

    self.assertNotIn(self.INVALID_TYPE_ERROR, cm.exception.result.error)

  def testCheckOptionsRequiresGSPathForGCETests(self):
    """Tests that CheckOptions requires a valid GS path for GCE tests."""
    local_path = '/tmp/foo/bar'
    gs_path = 'gs://foo-bucket/bar.tar.gz'
    cmd = [os.path.join(constants.CROSUTILS_DIR, 'bin', 'cros_au_test_harness'),
           '--type=gce',
           '--target_image=%s' % local_path
          ]
    with self.assertRaises(cros_build_lib.RunCommandError) as cm:
      cros_build_lib.RunCommand(cmd)
    self.assertIn(self.INVALID_IMAGE_PATH, cm.exception.result.error)

    cmd = [os.path.join(constants.CROSUTILS_DIR, 'bin', 'cros_au_test_harness'),
           '--type=gce',
           '--target_image=%s' % gs_path
          ]
    with self.assertRaises(cros_build_lib.RunCommandError) as cm:
      cros_build_lib.RunCommand(cmd)
    self.assertNotIn(self.INVALID_IMAGE_PATH, cm.exception.result.error)

  @unittest.skip('This test runs but only for demo purposes. Do not check it '
                 'in as is')
  def testSimpleTestsOnGCE(self):
    """Tests that cros_au_test_harness is able to run simple tests on GCE.

    Explicitly triggers SimpleTestVerify and SimpleTestUpdateAndVerify via
    '--test_prefix'.
    """
    board = 'lakitu'
    gs_path = 'gs://test-images/chromiumos_test_image.tar.gz'
    test_results_dir = 'chroot/tmp/test_results_%s' % str(uuid.uuid4())
    cmd = [os.path.join(constants.CROSUTILS_DIR, 'bin', 'cros_au_test_harness'),
           '--type=gce',
           '--target_image=%s' % gs_path,
           '--board=%s' % board,
           '--test_results=%s' % test_results_dir,
           '--test_prefix=Simple',
           '--verify_suite_name=smoke',
           '--parallel'
          ]
    cros_build_lib.RunCommand(cmd)


if __name__ == '__main__':
  unittest.main()
