#!/usr/bin/python
#
# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test module containing unittests for CTest."""

import logging
import mox
import os
import shutil
import sys
import tempfile
import unittest

import constants
sys.path.append(constants.SOURCE_ROOT)
import chromite.lib.cros_build_lib as chromite_build_lib

import ctest

class ImageExtractorTest(mox.MoxTestBase):
  """Testing all'm image extractors."""
  def setUp(self):
    super(ImageExtractorTest, self).setUp()

    self.work_dir = tempfile.mkdtemp('ImageExtractorTest')
    self.build_name = 'x86-generic-full'
    # Set constants to be easily testable.
    ctest.ImageExtractor.LOCAL_ARCHIVE = os.path.join(self.work_dir, 'archive')
    ctest.ImageExtractor.SRC_ARCHIVE_DIR = os.path.join(self.work_dir, 'src')

    # Our test object.
    self.test_extractor = ctest.ImageExtractor(self.build_name)

    # Convenience variables for testing.
    self.archive_dir = os.path.join(ctest.ImageExtractor.LOCAL_ARCHIVE,
                                    self.build_name)
    self.src_archive = ctest.ImageExtractor.SRC_ARCHIVE_DIR
    self.mox.StubOutWithMock(logging, 'error')

  def tearDown(self):
    shutil.rmtree(self.work_dir)

  def CreateFakeArchiveDir(self, number_of_entries, add_build_number=False):
    """Creates a fake archive dir with specified number of entries."""
    # Create local board directory e.g. /var/archive/x86-generic-full.
    os.makedirs(self.archive_dir)
    # Create a latest file.
    open(os.path.join(self.archive_dir, 'LATEST'), 'w').close()
    version_s = 'R16-158.0.0-a1-b%d' if add_build_number else 'R16-158.0.%d-a1'
    # Create specified number of entries.
    for i in range(number_of_entries):
      new_dir = os.path.join(self.archive_dir, version_s % i)
      os.makedirs(new_dir)

  def testGetLatestImageWithNoEntries(self):
    """Should return None if the directory has no entries."""
    self.CreateFakeArchiveDir(0)
    latest_image = self.test_extractor.GetLatestImage('R16-158.0.11-a1')
    self.assertEqual(latest_image, None)

  def testGetLatestImageWithOldEntry(self):
    """Compatibility testing.  GetLatestImage should ignore old style entries.
    """
    self.CreateFakeArchiveDir(0)
    os.makedirs(os.path.join(self.archive_dir, '0-158.0.1-a1'))
    latest_image = self.test_extractor.GetLatestImage('R16-158.0.11-a1')
    self.assertEqual(latest_image, None)

  def testGetLatestImageWithBuildEntries(self):
    """The normal case with build#'s.  Return the path to the highest entry.

    Test both ways to mix version strings with and without build numbers.  We
    generate R16-158.0.0-a1-b[0-10] in the local archive and test again the
    target version R16-158.0.1-a1 and R16-158.0.0-a1-b11.  These both should
    return R16-158.0.0-a1-b10.
    """
    self.CreateFakeArchiveDir(11, add_build_number=True)
    latest_image = self.test_extractor.GetLatestImage('R16-158.0.1-a1')
    self.assertEqual(os.path.basename(latest_image), 'R16-158.0.0-a1-b10')
    latest_image = self.test_extractor.GetLatestImage('R16-158.0.0-a-b11')
    self.assertEqual(os.path.basename(latest_image), 'R16-158.0.0-a1-b10')

  def testGetLatestImageWithEntries(self):
    """The normal case.  Return the path to the highest entry."""
    self.CreateFakeArchiveDir(11)
    # Throw in a bad directory for good measure.
    os.makedirs(os.path.join(self.archive_dir, '0-158.0.1-a1'))
    latest_image = self.test_extractor.GetLatestImage('R16-158.0.11-a1')
    self.assertEqual(os.path.basename(latest_image), 'R16-158.0.10-a1')

  def testGetLatestImageWithEntriesAndTarget(self):
    """The normal case but we pass in a target_version.

    Returns the path to the highest entry before target and spits out a
    logging error saying that 10 is too high.
    """
    self.CreateFakeArchiveDir(11)
    os.makedirs(os.path.join(self.archive_dir, 'R16-158.0.9-a1-b123'))
    logging.error(mox.StrContains('R16-158.0.10-a1'))
    self.mox.ReplayAll()
    latest_image = self.test_extractor.GetLatestImage('R16-158.0.9-a1')
    self.assertEqual(os.path.basename(latest_image), 'R16-158.0.8-a1')
    self.mox.VerifyAll()

  def testUnzipImageArchiveAlready(self):
    """Ensure we create a new archive and delete the old one."""
    old_entry = os.path.join(self.src_archive, 'R16-158.0.0-a1')
    new_entry = os.path.join(self.src_archive, 'R16-158.0.1-a1')
    os.makedirs(old_entry)

    self.mox.StubOutWithMock(chromite_build_lib, 'RunCommand')
    chromite_build_lib.RunCommand(mox.In('unzip'), print_cmd=False)

    self.mox.ReplayAll()
    self.test_extractor.UnzipImage(os.path.join(self.archive_dir,
                                                'R16-158.0.1-a1'))
    self.mox.VerifyAll()
    self.assertFalse(os.path.exists(old_entry))
    self.assertTrue(os.path.exists(new_entry))

  def testUnzipImageNoArchive(self):
    """Ensure we create a new archive with none before."""
    new_entry = os.path.join(self.src_archive, 'R16-158.0.1-a1')

    self.mox.StubOutWithMock(chromite_build_lib, 'RunCommand')
    chromite_build_lib.RunCommand(mox.In('unzip'), print_cmd=False)

    self.mox.ReplayAll()
    self.test_extractor.UnzipImage(os.path.join(self.archive_dir,
                                                'R16-158.0.1-a1'))
    self.mox.VerifyAll()
    self.assertTrue(os.path.exists(new_entry))


class CTestTest(mox.MoxTestBase):
  """Testing the test-worthy methods in CTest."""

  def testFindTargetAndBaseImagesNoBaseNoArchive(self):
    """Tests whether we can set the right vars if no Base image found.

    If no base is found and there is no latest image, we should test the target
    against the base.
    """
    self.mox.StubOutWithMock(ctest.CTest, '__init__')
    self.mox.StubOutWithMock(ctest.ImageExtractor, 'GetLatestImage')

    # TODO(sosa): Can we create mock objects but call a real method in an easier
    # way?
    ctest.CTest.__init__()
    ctest.ImageExtractor.GetLatestImage('target_version').AndReturn(None)

    self.mox.ReplayAll()
    ctester = ctest.CTest() # Calls mocked out __init__.
    ctester.target = 'some_image/target_version/file.bin'
    ctester.base = None
    ctester.build_config = 'x86-generic-full'
    ctester.FindTargetAndBaseImages()
    self.mox.VerifyAll()
    self.assertEqual(ctester.base, ctester.target)

  def testFindTargetAndBaseImagesBaseWithLatest(self):
    """Tests whether we can set the right vars if base image found in archive.

    Tests whether if we find a latest image, that we unzip it and set the
    base accordingly.
    """
    self.mox.StubOutWithMock(ctest.CTest, '__init__')
    self.mox.StubOutWithMock(ctest.ImageExtractor, 'GetLatestImage')
    self.mox.StubOutWithMock(ctest.ImageExtractor, 'UnzipImage')

    latest_base_dir = '/some/fake/path'
    latest_base_path = os.path.join('/some/fake/path',
                                    ctest.ImageExtractor.IMAGE_TO_EXTRACT)

    ctest.CTest.__init__()
    ctest.ImageExtractor.GetLatestImage('target_version').AndReturn(
        latest_base_dir)
    ctest.ImageExtractor.UnzipImage(latest_base_dir).AndReturn(latest_base_path)

    self.mox.ReplayAll()
    ctester = ctest.CTest() # Calls mocked out __init__.
    ctester.target = 'some_image/target_version/file.bin'
    ctester.base = None
    ctester.build_config = 'x86-generic-full'
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
    self.mox.StubOutWithMock(ctest.ImageExtractor, 'GetLatestImage')
    fake_result = self.mox.CreateMock(chromite_build_lib.CommandResult)
    fake_result.output = '/some/path_to/latest_version'

    fake_crosutils = '/fake/root/src/scripts'

    ctest.CTest.__init__()
    chromite_build_lib.RunCommand(
        mox.In('./get_latest_image.sh'), cwd=fake_crosutils, print_cmd=False,
        redirect_stdout=True).AndReturn(fake_result)
    ctest.ImageExtractor.GetLatestImage('latest_version').AndReturn(None)

    self.mox.ReplayAll()
    ctester = ctest.CTest() # Calls mocked out __init__.
    ctester.target = None
    ctester.base = None
    ctester.build_config = 'x86-generic-full'
    ctester.board = 'board'
    ctester.crosutils_root = fake_crosutils
    ctester.FindTargetAndBaseImages()
    self.mox.VerifyAll()
    self.assertEqual(ctester.base, ctester.target)
    self.assertEqual(ctester.base, os.path.join(
        fake_result.output, ctest.ImageExtractor.IMAGE_TO_EXTRACT))


if __name__ == '__main__':
  unittest.main()
