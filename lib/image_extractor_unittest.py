#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing unittests for the image_extractor module."""

import logging
import mox
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

import constants
sys.path.append(constants.SOURCE_ROOT)
from chromite.lib import cros_build_lib

import image_extractor


class ImageExtractorTest(mox.MoxTestBase):
  """Testing all'm image extractors."""
  def setUp(self):
    super(ImageExtractorTest, self).setUp()

    self.work_dir = tempfile.mkdtemp('ImageExtractorTest')
    self.board = 'x86-generic-full'
    # Set constants to be easily testable.
    self.archive_dir = os.path.join(self.work_dir, 'archive', self.board)
    image_extractor.ImageExtractor.SRC_ARCHIVE_DIR = os.path.join(self.work_dir,
                                                                  'src')
    # Our test object.
    self.test_extractor = image_extractor.ImageExtractor(self.archive_dir)

    # Convenience variables for testing.
    self.src_archive = image_extractor.ImageExtractor.SRC_ARCHIVE_DIR
    self.mox.StubOutWithMock(logging, 'error')

  def tearDown(self):
    shutil.rmtree(self.work_dir)

  @staticmethod
  def _TouchImageZip(directory):
    if not os.path.exists(directory):
      os.makedirs(directory)

    zipname = os.path.join(directory, 'image.zip')
    with zipfile.ZipFile(zipname, 'w'):
      pass

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
      ImageExtractorTest._TouchImageZip(new_dir)

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
    latest_image = self.test_extractor.GetLatestImage('R16-158.0.0-a1-b11')
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
    logging.error(mox.IgnoreArg(), 'R16-158.0.10-a1')
    self.mox.ReplayAll()
    latest_image = self.test_extractor.GetLatestImage('R16-158.0.9-a1')
    self.assertEqual(os.path.basename(latest_image), 'R16-158.0.8-a1')
    self.mox.VerifyAll()

  def testUnzipImageArchiveAlready(self):
    """Ensure we create a new archive and delete the old one."""
    old_entry = os.path.join(self.src_archive, self.board, 'R16-158.0.0-a1')
    os.makedirs(old_entry)
    new_entry = os.path.join(self.src_archive, self.board, 'R16-158.0.1-a1')
    archived_image_dir = os.path.join(self.archive_dir, 'R16-158.0.1-a1')
    ImageExtractorTest._TouchImageZip(archived_image_dir)

    self.mox.StubOutWithMock(cros_build_lib, 'RunCommand')
    cros_build_lib.RunCommand(mox.In('unzip'), print_cmd=False)

    self.mox.ReplayAll()
    self.test_extractor.UnzipImage(archived_image_dir)
    self.mox.VerifyAll()
    self.assertFalse(os.path.exists(old_entry))
    self.assertTrue(os.path.exists(new_entry))

  def testUnzipImageNoArchive(self):
    """Ensure we create a new archive with none before."""
    new_entry = os.path.join(self.src_archive, self.board, 'R16-158.0.1-a1')
    archived_image_dir = os.path.join(self.archive_dir, 'R16-158.0.1-a1')
    ImageExtractorTest._TouchImageZip(archived_image_dir)

    self.mox.StubOutWithMock(cros_build_lib, 'RunCommand')
    cros_build_lib.RunCommand(mox.In('unzip'), print_cmd=False)

    self.mox.ReplayAll()
    self.test_extractor.UnzipImage(archived_image_dir)
    self.mox.VerifyAll()
    self.assertTrue(os.path.exists(new_entry))

  def testBadZipImageArchive(self):
    """Ensure we ignore corrupt archives."""

    # Create valid archive followed by corrupt one.
    self.CreateFakeArchiveDir(2, add_build_number=True)
    bad_zip_name = os.path.join(
        self.archive_dir, 'R16-158.0.0-a1-b1', 'image.zip')
    with open(bad_zip_name, 'w') as f:
      f.write('oogabooga')

    # This is normally mox'd out to ensure it's never called, but we expect it.
    logging.error('Version in archive dir is corrupt: %s', 'R16-158.0.0-a1-b1')

    self.mox.ReplayAll()

    # Ensure we fine the first one (valid), not the second (corrupt)
    latest_image = self.test_extractor.GetLatestImage('R16-158.0.1-a1')
    self.assertEqual(os.path.basename(latest_image), 'R16-158.0.0-a1-b0')


if __name__ == '__main__':
  unittest.main()
