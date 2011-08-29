# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing python helper methods for testing."""

import glob
import logging
import multiprocessing
import os

import cros_build_lib


def CalculateDefaultJobs():
  """Calculate how many jobs to run in parallel by default."""
  # Since each job needs loop devices, limit our number of jobs to the
  # number of loop devices divided by two. Reserve six loop devices for
  # other processes (e.g. archiving the build in the background.)
  loop_count = len(glob.glob('/dev/loop*')) - 6
  cpu_count = multiprocessing.cpu_count()
  return max(1, min(cpu_count, loop_count / 2))


def CreateVMImage(image, board):
  """Returns the path of the image built to run in a VM.

  VM returned is a test image that can run full update testing on it.  This
  method does not return a new image if one already existed before.

  Args:
    image: Path to the image.
    board: Board that the image was built with.
  """
  vm_image_path = '%s/chromiumos_qemu_image.bin' % os.path.dirname(image)
  if not os.path.exists(vm_image_path):
    logging.info('Creating %s' % vm_image_path)
    cros_build_lib.RunCommand(
        ['./image_to_vm.sh',
         '--full',
         '--from=%s' % cros_build_lib.ReinterpretPathForChroot(
             os.path.dirname(image)),
         '--board=%s' % board,
         '--test_image'
         ], enter_chroot=True, cwd=cros_build_lib.GetCrosUtilsPath())

  assert os.path.exists(vm_image_path), 'Failed to create the VM image.'
  return vm_image_path


def SetupCommonLoggingFormat():
  """Sets up common logging format for the logging module."""
  logging_format = '%(asctime)s - %(filename)s - %(levelname)-8s: %(message)s'
  date_format = '%Y/%m/%d %H:%M:%S'
  logging.basicConfig(level=logging.DEBUG, format=logging_format,
                      datefmt=date_format)
