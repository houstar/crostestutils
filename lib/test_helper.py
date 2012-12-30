# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing python helper methods for testing."""

import glob
import logging
import multiprocessing
import os

import constants
from chromite.lib import cros_build_lib
from chromite.lib import git


def _GetTotalMemoryGB():
  """Calculate total memory on this machine, in gigabytes."""
  res = cros_build_lib.RunCommandCaptureOutput(['free', '-g'], print_cmd=False)
  assert res.returncode == 0
  for line in res.output.splitlines():
    if line.startswith('Mem:'):
      return int(line.split()[1])
  raise Exception('Could not calculate total memory')


def CalculateDefaultJobs():
  """Calculate how many jobs to run in parallel by default."""

  # 1. Since each job needs two loop devices, limit our number of jobs to the
  #    number of loop devices divided by two. Reserve six loop devices for
  #    other processes (e.g. archiving the build in the background.)
  # 2. Reserve 10GB RAM for background processes. After that, each job needs
  #    ~2GB RAM.
  # 3. Reserve half the CPUs for background processes.
  loop_count = (len(glob.glob('/dev/loop*')) - 6) / 2
  cpu_count = multiprocessing.cpu_count() / 2
  mem_count = int((_GetTotalMemoryGB() - 10) / 2)
  return max(1, min(cpu_count, mem_count, loop_count))


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
    logging.info('Creating %s', vm_image_path)
    cros_build_lib.RunCommand(
        ['./image_to_vm.sh',
         '--full',
         '--from=%s' % git.ReinterpretPathForChroot(os.path.dirname(image)),
         '--board=%s' % board,
         '--test_image'
        ], enter_chroot=True, cwd=constants.SOURCE_ROOT)

  assert os.path.exists(vm_image_path), 'Failed to create the VM image.'
  return vm_image_path


def SetupCommonLoggingFormat():
  """Sets up common logging format for the logging module."""
  logging_format = '%(asctime)s - %(filename)s - %(levelname)-8s: %(message)s'
  date_format = '%Y/%m/%d %H:%M:%S'
  logging.basicConfig(level=logging.DEBUG, format=logging_format,
                      datefmt=date_format)
