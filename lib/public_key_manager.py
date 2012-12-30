# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module manages interactions between an image and a public key."""

import os
import tempfile

import constants
from chromite.lib import cros_build_lib
from chromite.lib import git
from chromite.lib import osutils


def MountImage(image_path, root_dir, stateful_dir, read_only):
  """Mounts a Chromium OS image onto mount dir points."""
  from_dir, image = os.path.split(image_path)
  cmd = ['./mount_gpt_image.sh',
         '--from=%s' % from_dir,
         '--image=%s' % image,
         '--rootfs_mountpt=%s' % root_dir,
         '--stateful_mountpt=%s' % stateful_dir]
  if read_only: cmd.append('--read_only')
  cros_build_lib.RunCommandCaptureOutput(
      cmd, print_cmd=False, cwd=constants.CROSUTILS_DIR)


def UnmountImage(root_dir, stateful_dir):
  """Unmounts a Chromium OS image specified by mount dir points."""
  cmd = ['./mount_gpt_image.sh', '--unmount', '--rootfs_mountpt=%s' % root_dir,
         '--stateful_mountpt=%s' % stateful_dir]
  cros_build_lib.RunCommandCaptureOutput(
      cmd, print_cmd=False, cwd=constants.CROSUTILS_DIR)


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
      MountImage(image_path, self._rootfs_dir, self._stateful_dir,
                 read_only=True)
      self._full_target_key_path = os.path.join(
          self._rootfs_dir, PublicKeyManager.TARGET_KEY_PATH)
      self._is_key_new = True
      if os.path.exists(self._full_target_key_path):
        cmd = ['diff', self.key_path, self._full_target_key_path]
        res = cros_build_lib.RunCommandCaptureOutput(
            cmd, print_cmd=False, error_code_ok=True)
        if not res.output: self._is_key_new = False

    finally:
      UnmountImage(self._rootfs_dir, self._stateful_dir)

  def __del__(self):
    """Remove our temporary directories we created in init."""
    os.rmdir(self._rootfs_dir)
    os.rmdir(self._stateful_dir)

  def AddKeyToImage(self):
    """Adds the key specified in init to the image."""
    if not self._is_key_new:
      cros_build_lib.Info('Public key already on image %s.  No work to do.',
                          self.image_path)
      return

    cros_build_lib.Info('Copying %s into %s', self.key_path, self.image_path)
    try:
      MountImage(self.image_path, self._rootfs_dir, self._stateful_dir,
                 read_only=False)
      dir_path = os.path.dirname(self._full_target_key_path)
      osutils.SafeMakedirs(dir_path, sudo=True)
      cmd = ['cp', '--force', '-p', self.key_path, self._full_target_key_path]
      cros_build_lib.SudoRunCommand(cmd)
    finally:
      UnmountImage(self._rootfs_dir, self._stateful_dir)
      self._MakeImageBootable()

  def _MakeImageBootable(self):
    """Makes the image bootable.  Note, it is only useful for non-vm images."""
    from_dir, image = os.path.split(self.image_path)
    if 'qemu' not in image:
      from_dir = git.ReinterpretPathForChroot(from_dir)
      cmd = ['bin/cros_make_image_bootable', from_dir, image,
             '--force_developer_mode']
      cros_build_lib.RunCommandCaptureOutput(
          cmd, print_cmd=False, enter_chroot=True, cwd=constants.SOURCE_ROOT)
