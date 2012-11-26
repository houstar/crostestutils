#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test module containing unittests for CTest."""

import mox
import os
import sys
import unittest

import constants
sys.path.append(constants.SOURCE_ROOT)
sys.path.append(constants.CROS_PLATFORM_ROOT)
import chromite.lib.cros_build_lib as chromite_build_lib

import ctest
from crostestutils.lib import image_extractor


class CTestTest(mox.MoxTestBase):
  """Testing the test-worthy methods in CTest."""

  FAKE_ROOT = '/fake/root'
  ARCHIVE_DIR = os.path.join(FAKE_ROOT, 'x86-generic-full')

  def testFindTargetAndBaseImagesNoBaseNoArchive(self):
    """Tests whether we can set the right vars if no Base image found.

    If no base is found and there is no latest image, we should test the target
    against the base.
    """
    self.mox.StubOutWithMock(ctest.CTest, '__init__')
    self.mox.StubOutWithMock(image_extractor.ImageExtractor, 'GetLatestImage')

    # TODO(sosa): Can we create mock objects but call a real method in an easier
    # way?
    ctest.CTest.__init__()
    image_extractor.ImageExtractor.GetLatestImage(
        'target_version').AndReturn(None)

    self.mox.ReplayAll()
    ctester = ctest.CTest() # Calls mocked out __init__.
    ctester.target = 'some_image/target_version/file.bin'
    ctester.base = None
    ctester.archive_dir = self.ARCHIVE_DIR
    ctester.FindTargetAndBaseImages()
    self.mox.VerifyAll()
    self.assertEqual(ctester.base, ctester.target)

  def testFindTargetAndBaseImagesBaseWithLatest(self):
    """Tests whether we can set the right vars if base image found in archive.

    Tests whether if we find a latest image, that we unzip it and set the
    base accordingly.
    """
    self.mox.StubOutWithMock(ctest.CTest, '__init__')
    self.mox.StubOutWithMock(image_extractor.ImageExtractor, 'GetLatestImage')
    self.mox.StubOutWithMock(image_extractor.ImageExtractor, 'UnzipImage')

    latest_base_dir = '/some/fake/path'
    latest_base_path = os.path.join(
        '/some/fake/path', image_extractor.ImageExtractor.IMAGE_TO_EXTRACT)

    ctest.CTest.__init__()
    image_extractor.ImageExtractor.GetLatestImage('target_version').AndReturn(
        latest_base_dir)
    image_extractor.ImageExtractor.UnzipImage(latest_base_dir).AndReturn(
        latest_base_path)

    self.mox.ReplayAll()
    ctester = ctest.CTest() # Calls mocked out __init__.
    ctester.target = 'some_image/target_version/file.bin'
    ctester.base = None
    ctester.archive_dir = self.ARCHIVE_DIR
    ctester.FindTargetAndBaseImages()
    self.mox.VerifyAll()
    self.assertEqual(ctester.base, latest_base_path)

  def testFindTargetAndBaseImagesBaseNothingSetSimple(self):
    """Tests whether we can set the right vars if no target or base set.

    Tests whether if there is no local archive and no target set, vars are set
    correctly.  This means target should be inferred and base should be set to
    target.
    """
    self.mox.StubOutWithMock(chromite_build_lib, 'RunCommand')
    self.mox.StubOutWithMock(ctest.CTest, '__init__')
    self.mox.StubOutWithMock(image_extractor.ImageExtractor, 'GetLatestImage')
    fake_result = self.mox.CreateMock(chromite_build_lib.CommandResult)
    fake_result.output = '/some/path_to/latest_version'

    fake_crosutils = os.path.join(self.FAKE_ROOT, 'src', 'scripts')

    ctest.CTest.__init__()
    chromite_build_lib.RunCommand(
        mox.In('./get_latest_image.sh'), cwd=fake_crosutils, print_cmd=False,
        redirect_stdout=True).AndReturn(fake_result)
    image_extractor.ImageExtractor.GetLatestImage('latest_version').AndReturn(
        None)

    self.mox.ReplayAll()
    ctester = ctest.CTest() # Calls mocked out __init__.
    ctester.target = None
    ctester.base = None
    ctester.archive_dir = self.ARCHIVE_DIR
    ctester.board = 'board'
    ctester.crosutils_root = fake_crosutils
    ctester.FindTargetAndBaseImages()
    self.mox.VerifyAll()
    self.assertEqual(ctester.base, ctester.target)
    self.assertEqual(ctester.base, os.path.join(
        fake_result.output, image_extractor.ImageExtractor.IMAGE_TO_EXTRACT))


if __name__ == '__main__':
  unittest.main()
