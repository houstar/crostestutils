# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module manages interactions between an image and a public key."""

from __future__ import print_function

import os
import tempfile

import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_logging as logging
from chromite.lib import osutils
from chromite.lib import path_util
from crostestutils.lib import mount_helper


class PublicKeyManager(object):
  """Class wrapping interactions with a public key on an image."""
  TARGET_KEY_PATH = 'usr/share/update_engine/update-payload-key.pub.pem'

  def __init__(self, image_path, key_path):
    """Initializes a manager with image_path and key_path we plan to insert."""
    self.image_path = image_path
    self.key_path = key_path
    self._rootfs_dir = tempfile.mkdtemp(suffix='rootfs', prefix='tmp')
    self._stateful_dir = tempfile.mkdtemp(suffix='stateful', prefix='tmp')

    # Gather some extra information about the image.
    try:
      mount_helper.MountImage(image_path, self._rootfs_dir, self._stateful_dir,
                              read_only=True)
      self._full_target_key_path = os.path.join(
          self._rootfs_dir, PublicKeyManager.TARGET_KEY_PATH)
      self._is_key_new = True
      if os.path.exists(self._full_target_key_path):
        cmd = ['diff', self.key_path, self._full_target_key_path]
        res = cros_build_lib.RunCommand(
            cmd, print_cmd=False, error_code_ok=True, capture_output=True)
        if not res.output:
          self._is_key_new = False

    finally:
      mount_helper.UnmountImage(self._rootfs_dir, self._stateful_dir)

  def __del__(self):
    """Remove our temporary directories we created in init."""
    os.rmdir(self._rootfs_dir)
    os.rmdir(self._stateful_dir)

  def AddKeyToImage(self):
    """Adds the key specified in init to the image."""
    if not self._is_key_new:
      logging.info('Public key already on image %s.  No work to do.',
                   self.image_path)
      return

    logging.info('Copying %s into %s', self.key_path, self.image_path)
    try:
      mount_helper.MountImage(self.image_path, self._rootfs_dir,
                              self._stateful_dir, read_only=False)
      dir_path = os.path.dirname(self._full_target_key_path)
      osutils.SafeMakedirs(dir_path, sudo=True)
      cmd = ['cp', '--force', '-p', self.key_path, self._full_target_key_path]
      cros_build_lib.SudoRunCommand(cmd)
    finally:
      mount_helper.UnmountImage(self._rootfs_dir, self._stateful_dir)
      self._MakeImageBootable()

  def _MakeImageBootable(self):
    """Makes the image bootable.  Note, it is only useful for non-vm images."""
    from_dir, image = os.path.split(self.image_path)
    if 'qemu' not in image:
      from_dir = path_util.ToChrootPath(from_dir)
      cmd = ['bin/cros_make_image_bootable', from_dir, image,
             '--force_developer_mode']
      cros_build_lib.RunCommand(
          cmd, print_cmd=False, enter_chroot=True, cwd=constants.SOURCE_ROOT,
          capture_output=True)
