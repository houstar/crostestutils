# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing class that implements an au_worker for GCE instances."""

from __future__ import print_function

import datetime
import time

from multiprocessing import Process

from chromite.compute import gcloud
from chromite.lib import cros_build_lib
from chromite.lib import cros_logging as logging
from crostestutils.au_test_harness import au_worker
from crostestutils.au_test_harness import constants
from crostestutils.au_test_harness import update_exception


class GCEAUWorker(au_worker.AUWorker):
  """Test harness for updating GCE instances."""

  _INSTANCE_PREFIX = 'test-instance-'
  _IMAGE_PREFIX = 'test-image-'

  def __init__(self, options, test_results_root, project=constants.GCE_PROJECT,
               zone=constants.GCE_ZONE):
    """Processes GCE-specific options."""
    super(GCEAUWorker, self).__init__(options, test_results_root)

    # Google Cloud project and zone, in which to create the test instance.
    self.gccontext = gcloud.GCContext(project, zone)
    self.image = ''
    self.instance = ''
    self.instance_ip = ''

    # Background processes that delete throw-away instances.
    self.bg_delete_processes = []

  def CleanUp(self):
    """Deletes throw-away instances and images"""
    logging.info('Waiting for all instances and images to be deleted.')

    def _WaitForBackgroundDeleteProcesses():
      for p in self.bg_delete_processes:
        p.join()

    _WaitForBackgroundDeleteProcesses()
    # Delete the instance/image created by the last call to UpdateImage.
    self._DeleteExistingInstanceInBackground()
    _WaitForBackgroundDeleteProcesses()
    logging.info('All instances/images are deleted.')

  def _DeleteExistingInstanceInBackground(self):
    """Deletes existing instances if any."""

    def _DeleteInstance():
      bg_delete = Process(target=self.gccontext.DeleteInstance,
                          args=(self.instance,), kwargs=dict(quiet=True))
      bg_delete.start()
      self.bg_delete_processes.append(bg_delete)
      self.instance = ''
      self.instance_ip = ''

    def _DeleteImage():
      bg_delete = Process(target=self.gccontext.DeleteImage,
                          args=(self.image,), kwargs=dict(quiet=True))
      bg_delete.start()
      self.bg_delete_processes.append(bg_delete)
      self.image = ''

    if self.instance:
      logging.info('Existing instance %s found. Deleting...', self.instance)
      _DeleteInstance()
      if self.image:
        _DeleteImage()

  def PrepareBase(self, image_path, signed_base=False):
    """Auto-update to base image to prepare for test."""
    return self.PrepareRealBase(image_path, signed_base)

  def UpdateImage(self, image_path, src_image_path='', stateful_change='old',
                  proxy_port=None, private_key_path=None):
    """Updates the image on a GCE instance.

    Unlike real_au_worker, this method always creates a new instance. Note that
    |image_path| has to be a valid Google Cloud Storage url, e.g.,
    gs://foo-bucket/bar.tar.gz.
    """
    self._DeleteExistingInstanceInBackground()
    ts = datetime.datetime.fromtimestamp(time.time()).strftime(
        '%Y-%m-%d-%H-%M-%S')
    image = '%s%s' % (self._IMAGE_PREFIX, ts)
    instance = '%s%s' % (self._INSTANCE_PREFIX, ts)

    # Create an image from |image_path| and an instance from the image.
    try:
      self.gccontext.CreateImage(image, image_path)
      self.gccontext.CreateInstance(instance, image)
    except gcloud.GCCommandError as e:
      raise update_exception.UpdateException(
          1, 'Update failed. Error: %s' % e.message)
    self.instance_ip = self.gccontext.GetInstanceIP(instance)
    self.instance = instance
    self.image = image

  def VerifyImage(self, unittest, percent_required_to_pass=100, test=''):
    """Verifies an image using test_that with verification suite."""
    test_directory, _ = self.GetNextResultsPath('autotest_tests')
    if not test:
      test = self.verify_suite

    self.TestInfo('Running test %s to verify image.' % test)

    cmd = ['test_that', '--no-quickmerge', '--results_dir=%s' % test_directory,
           self.instance_ip, test]
    if self.ssh_private_key is not None:
      cmd.append('--ssh_private_key=%s' % self.ssh_private_key)

    result = cros_build_lib.RunCommand(cmd, error_code_ok=True,
                                       enter_chroot=True, redirect_stdout=True,
                                       cwd=constants.CROSUTILS_DIR)
    ret = self.AssertEnoughTestsPassed(unittest, result.output,
                                       percent_required_to_pass)
    if not ret:
      self._DeleteExistingInstanceInBackground()

    return ret
