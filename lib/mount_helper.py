# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Module containing helper methods for mounting and unmounting an image.

import os

import constants
from chromite.lib import cros_build_lib

def MountImage(image_path, root_dir, stateful_dir, read_only, safe=False):
  """Mounts a Chromium OS image onto mount dir points."""
  from_dir, image = os.path.split(image_path)
  cmd = ['./mount_gpt_image.sh',
         '--from=%s' % from_dir,
         '--image=%s' % image,
         '--rootfs_mountpt=%s' % root_dir,
         '--stateful_mountpt=%s' % stateful_dir]
  if read_only: cmd.append('--read_only')
  if safe: cmd.append('--safe')
  cros_build_lib.RunCommand(
      cmd, print_cmd=False, cwd=constants.CROSUTILS_DIR, capture_output=True)


def UnmountImage(root_dir, stateful_dir):
  """Unmounts a Chromium OS image specified by mount dir points."""
  cmd = ['./mount_gpt_image.sh', '--unmount', '--rootfs_mountpt=%s' % root_dir,
         '--stateful_mountpt=%s' % stateful_dir]
  cros_build_lib.RunCommand(
      cmd, print_cmd=False, cwd=constants.CROSUTILS_DIR, capture_output=True)
