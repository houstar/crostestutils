# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing class to extract the latest image for a build."""

import distutils.version
import logging
import os
import re
import shutil

import chromite.lib.cros_build_lib as chromite_build_lib


class ImageExtractor(object):
  """Class used to get the latest image for the board."""
  # Archive directory the buildbot stores images.
  LOCAL_ARCHIVE = '/b/archive'
  # The image we want to test.
  IMAGE_TO_EXTRACT = 'chromiumos_test_image.bin'
  # Archive directory in the src tree to keep latest archived image after
  # we've unzipped them.
  SRC_ARCHIVE_DIR = 'latest_image'

  def __init__(self, build_config):
    """Initializes a extractor for the build_config."""
    self.archive = os.path.join(self.LOCAL_ARCHIVE, build_config)

  def GetLatestImage(self, target_version):
    """Gets the last image archived for the board.

    Args:
      target_version:  The version that is being tested.  The archive
        directory may be being populated with the results of this version
        while we're running so we shouldn't use it as the last image archived.
    """
    if os.path.exists(self.archive):
      my_re = re.compile(r'R\d+-(\d+)\.(\d+)\.(\d+).*')
      filelist = []
      target_lv = distutils.version.LooseVersion(target_version)
      for filename in os.listdir(self.archive):
        lv = distutils.version.LooseVersion(filename)
        if my_re.match(filename):
          if lv < target_lv:
            filelist.append(lv)
          elif not filename.startswith(target_version):
            logging.error('Version in archive dir is too new: %s' % filename)
      if filelist:
        return os.path.join(self.archive, str(max(filelist)))

    return None

  def UnzipImage(self, image_dir):
    """Unzips the image.zip from the image_dir and returns the image."""
    # We include the dirname of the image here so that we don't have to
    # re-unzip the same one each time.
    local_path = os.path.join(self.SRC_ARCHIVE_DIR,
                              os.path.basename(image_dir))
    image_to_return = os.path.abspath(os.path.join(local_path,
                                                   self.IMAGE_TO_EXTRACT))
    # We only unzip it if we don't have it.
    if not os.path.exists(image_to_return):
      # We don't want to keep test self.SRC_ARCHIVE_DIRs around.
      if os.path.exists(self.SRC_ARCHIVE_DIR):
        logging.info('Removing old archive from %s', self.SRC_ARCHIVE_DIR)
        shutil.rmtree(self.SRC_ARCHIVE_DIR)

      logging.info('Creating directory %s to store image for testing.',
                   local_path)
      os.makedirs(local_path)
      zip_path = os.path.join(image_dir, 'image.zip')
      logging.info('Unzipping image from %s', zip_path)
      chromite_build_lib.RunCommand(['unzip', '-d', local_path, zip_path],
                                    print_cmd=False)

    return image_to_return
