# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing class to extract the latest image for a build."""

import distutils.version
import logging
import os
import re
import shutil
import zipfile

from chromite.lib import cros_build_lib


class ImageExtractor(object):
  """Class used to get the latest image for the board."""
  # The default image to extract.
  IMAGE_TO_EXTRACT = 'chromiumos_test_image.bin'
  # Archive directory in the src tree to keep latest archived image after
  # we've unzipped them.
  SRC_ARCHIVE_DIR = 'latest_image'

  def __init__(self, archive_dir, image_to_extract=None):
    """Initializes a extractor for the archive_dir."""
    self.archive = archive_dir
    if not image_to_extract:
      image_to_extract = self.IMAGE_TO_EXTRACT
    self.image_to_extract = image_to_extract

  def ValidateZip(self, zip_image):
    """Validate that a zipped image is not corrupt.

    Args:
      zip_image:

    Returns:
      True if valid, else False.
    """

    try:
      # These two lines will either return the name of the first bad file
      # inside the zip, or raise an exception if it doesn't look like a valid
      # zip at all.
      zf = zipfile.ZipFile(zip_image)
      return zf.testzip() == None
    except zipfile.BadZipfile:
      return False

  def GetLatestImage(self, target_version):
    """Gets the last image archived for the board.

    Args:
      target_version: The version that is being tested.  The archive
        directory may be being populated with the results of this version
        while we're running so we shouldn't use it as the last image archived.
    """
    logging.info('Searching for previously generated images in %s ... ',
                 self.archive)
    if os.path.exists(self.archive):
      my_re = re.compile(r'R\d+-(\d+)\.(\d+)\.(\d+).*')
      filelist = []
      target_lv = distutils.version.LooseVersion(target_version)
      for filename in os.listdir(self.archive):
        lv = distutils.version.LooseVersion(filename)
        if my_re.match(filename):
          zip_image = os.path.join(self.archive, filename, 'image.zip')
          if lv < target_lv and os.path.exists(zip_image):
            if self.ValidateZip(zip_image):
              filelist.append(lv)
            else:
              logging.error('Version in archive dir is corrupt: %s', filename)

          elif not filename.startswith(target_version):
            logging.error('Version in archive dir is too new: %s', filename)
      if filelist:
        return os.path.join(self.archive, str(max(filelist)))

    logging.warn('Could not find a previously generated image on this host.')
    return None

  def UnzipImage(self, image_dir):
    """Unzips the image.zip from the image_dir and returns the image.

    This method unzips the image under SRC_ARCHIVE_DIR along with its version
    string. In order to save time, if it is attempting
    to re-unzip the same image with the same version string, it uses the
    cached image in SRC_ARCHIVE_DIR. It determines the version string based
    on the last path parts of the image_dir.

    Args:
      image_dir: Directory with image to unzip.

    Returns:
      The path to the image.bin file after it has been unzipped.

    Raises:
      MissingImageZipException if there is nothing to unzip within
      the image_dir.
    """
    # Use the last 2 paths as the version_string path (may include board id).
    version_string = os.path.join(*image_dir.split(os.path.sep)[-2:])
    cached_dir = os.path.join(ImageExtractor.SRC_ARCHIVE_DIR, version_string)
    cached_image = os.path.abspath(os.path.join(
        cached_dir, self.image_to_extract))
    # If we previously unzipped the image, we're done.
    if os.path.exists(cached_image):
      logging.info('Re-using image with version %s that we previously '
                   'unzipped to %s.', version_string, cached_image)
    else:
      # Cached image for version not found. Unzipping image from archive.
      if os.path.exists(ImageExtractor.SRC_ARCHIVE_DIR):
        logging.info('Removing previously archived images from %s',
                     ImageExtractor.SRC_ARCHIVE_DIR)
        shutil.rmtree(ImageExtractor.SRC_ARCHIVE_DIR)

      os.makedirs(cached_dir)
      zip_path = os.path.join(image_dir, 'image.zip')
      logging.info('Unzipping image from %s to %s', zip_path, cached_dir)
      cros_build_lib.RunCommand(['unzip', '-d', cached_dir, zip_path],
                                print_cmd=False)

    return cached_image
