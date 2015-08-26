# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing class that implements an au_worker for GCE instances."""

from __future__ import print_function

import datetime
import os
import shutil
import time

from multiprocessing import Process

from chromite.lib import cros_build_lib
from chromite.lib import cros_logging as logging
from chromite.lib import gs
from chromite.lib import path_util
from crostestutils.au_test_harness import au_worker
from crostestutils.au_test_harness import constants
from crostestutils.au_test_harness import update_exception
from crostestutils.lib import gce


class GCEAUWorker(au_worker.AUWorker):
  """Test harness for updating GCE instances.

  Attributes:
    gce_context: An utility for GCE operations.
    gscontext: An utility for GCS operations.
    gcs_bucket: The GCS bucket to upload image tarballs to.
    instance: A single VM instance associated with a worker.
    image: A single GCE image associated with a worker.
    tarball_local: Local path to the tarball of test image.
    tarball_remote: GCS path to the tarball of test image.
    bg_delete_processes:
      Background processes that delete stale instances and images.
  """

  INSTANCE_PREFIX = 'test-instance-'
  IMAGE_PREFIX = 'test-image-'
  GS_PATH_COMMON_PREFIX = 'gs://'
  GS_URL_COMMON_PREFIX = 'https://storage.googleapis.com/'

  def __init__(self, options, test_results_root,
               project=constants.GCE_PROJECT,
               zone=constants.GCE_DEFAULT_ZONE,
               network=constants.GCE_DEFAULT_NETWORK,
               json_key_file=constants.GCE_JSON_KEY,
               gcs_bucket=constants.GCS_BUCKET):
    """Processes GCE-specific options."""
    super(GCEAUWorker, self).__init__(options, test_results_root)
    self.gce_context = gce.GceContext.ForServiceAccount(
        project, zone, network, json_key_file=json_key_file)
    self.gscontext = gs.GSContext()
    self.gcs_bucket = gcs_bucket
    self.tarball_local = None
    self.tarball_remote = None
    self.instance = None
    self.image = None

    # Background processes that delete throw-away instances.
    self.bg_delete_processes = []

  def CleanUp(self):
    """Deletes throw-away instances and images"""
    logging.info('Waiting for all instances and images to be deleted.')

    def _WaitForBackgroundDeleteProcesses():
      for p in self.bg_delete_processes:
        p.join()
      self.bg_delete_processes = []

    _WaitForBackgroundDeleteProcesses()
    # Delete the instance/image created by the last call to UpdateImage.
    self._DeleteInstanceIfExists()
    _WaitForBackgroundDeleteProcesses()
    logging.info('All instances/images are deleted.')

  def _DeleteInstanceIfExists(self):
    """Deletes existing instances if any."""
    def _DeleteInstanceAndImage():
      self.gscontext.DoCommand(['rm', self.tarball_remote])
      self.gce_context.DeleteInstance(self.instance)
      self.gce_context.DeleteImage(self.image)

    if self.instance:
      logging.info('Existing instance %s found. Deleting...', self.instance)
      bg_delete = Process(target=_DeleteInstanceAndImage)
      bg_delete.start()
      self.bg_delete_processes.append(bg_delete)

  def PrepareBase(self, image_path, signed_base=False):
    """Auto-update to base image to prepare for test."""
    return self.PrepareRealBase(image_path, signed_base)

  def UpdateImage(self, image_path, src_image_path='', stateful_change='old',
                  proxy_port=None, payload_signing_key=None):
    """Updates the image on a GCE instance.

    Unlike real_au_worker, this method always creates a new instance.
    """
    self.tarball_local = image_path
    log_directory, fail_directory = self.GetNextResultsPath('update')
    self._DeleteInstanceIfExists()
    ts = datetime.datetime.fromtimestamp(time.time()).strftime(
        '%Y-%m-%d-%H-%M-%S')
    image = '%s%s' % (self.IMAGE_PREFIX, ts)
    instance = '%s%s' % (self.INSTANCE_PREFIX, ts)
    gs_directory = ('gs://%s/%s' % (self.gcs_bucket, ts))

    # Upload the GCE tarball to Google Cloud Storage.
    try:
      logging.info('Uploading GCE tarball %s to %s ...' , self.tarball_local,
                   gs_directory)
      self.gscontext.CopyInto(self.tarball_local, gs_directory)
      self.tarball_remote = '%s/%s' % (gs_directory,
                                       os.path.basename(self.tarball_local))
    except Exception as e:
      raise update_exception.UpdateException(
          1, 'Update failed. Unable to upload test image GCE tarball to GCS. '
          'Error: %s' % e)

    # Create an image from |image_path| and an instance from the image.
    try:
      image_link = self.gce_context.CreateImage(
          image, self._GsPathToUrl(self.tarball_remote))
      self.gce_context.CreateInstance(instance, image_link)
    except gce.Error as e:
      self._HandleFail(log_directory, fail_directory)
      raise update_exception.UpdateException(1, 'Update failed. Error: %s' % e)
    self.instance = instance
    self.image = image

  def VerifyImage(self, unittest, percent_required_to_pass=100, test=''):
    """Verifies an image using test_that with verification suite."""
    log_directory, fail_directory = self.GetNextResultsPath('autotest_tests')
    log_directory_in_chroot = log_directory.rpartition('chroot')[2]
    instance_ip = self.gce_context.GetInstanceIP(self.instance)
    test_suite = test or self.verify_suite

    cmd = ['test_that', '-b', self.board, '--no-quickmerge',
           '--results_dir=%s' % log_directory_in_chroot, instance_ip,
           test_suite]
    if self.ssh_private_key is not None:
      cmd.append('--ssh_private_key=%s' %
                 path_util.ToChrootPath(self.ssh_private_key))

    result = cros_build_lib.RunCommand(cmd, error_code_ok=True,
                                       enter_chroot=True, redirect_stdout=True,
                                       cwd=constants.CROSUTILS_DIR)
    ret = self.AssertEnoughTestsPassed(unittest, result.output,
                                       percent_required_to_pass)
    if not ret:
      self._HandleFail(log_directory, fail_directory)

    return ret

  def _HandleFail(self, log_directory, fail_directory):
    """Handles test failures.

    In case of a test failure, copy necessary files, i.e., the GCE tarball and
    ssh private key, to |fail_directory|, which will be later archived and
    uploaded to a GCS bucket by chromite.

    Args:
      log_directory: The root directory where test logs are stored.
      fail_directory: The directory to copy files to.
    """
    parent_dir = os.path.dirname(fail_directory)
    if not os.path.isdir(parent_dir):
      os.makedirs(parent_dir)

    # Copy logs. Must be done before moving image, as this creates
    # |fail_directory|.
    try:
      shutil.copytree(log_directory, fail_directory)
    except shutil.Error as e:
      logging.warning('Ignoring errors while copying logs: %s', e)

    # Copy GCE tarball and ssh private key for debugging.
    try:
      shutil.copy(self.tarball_local, fail_directory)
      if self.ssh_private_key is not None:
        shutil.copy(self.ssh_private_key, fail_directory)
    except shutil.Error as e:
      logging.warning('Ignoring errors while copying GCE tarball: %s', e)

    self._DeleteInstanceIfExists()

  def _GsPathToUrl(self, gs_path):
    """Converts a gs:// path to a URL.

    A formal URL is needed when creating an image from a GCS object.

    Args:
      gs_path: A GS path, e.g., gs://foo-bucket/bar.tar.gz.

    Returns:
      A GCS URL to the same object.

    Raises:
      ValueError if |gs_path| is not a valid GS path.
    """
    if not gs_path.startswith(self.GS_PATH_COMMON_PREFIX):
      raise ValueError('Invalid GCS path: %s' % gs_path)
    return gs_path.replace(self.GS_PATH_COMMON_PREFIX,
                           self.GS_URL_COMMON_PREFIX, 1)
