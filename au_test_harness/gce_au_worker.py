# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing a class that implements an au_worker for GCE instances.

By default GCEAUWorker creates a GCE instance with 'Default Instance Properties'
(detailed below), and runs the gce-smoke suite to verify an image. However it
allows customized test/suite list and instance properties, through an overlay
specific JSON file.

Default Instance Properties:
  project: constants.GCE_PROJECT
  zone: constants.GCE_DEFAULT_ZONE
  machine_type: n1-standard-8
  network: constants.GCE_DEFAULT_NETWORK
  other properties: GCE default.
    https://cloud.google.com/compute/docs/reference/latest/instances/insert

To run tests/suites other than the gce-smoke suite, and to specify the instance
properties, add gce_tests.json under <overlay>/scripts. Refer to _LoadTests for
the exact requirement of this file, but here is a short example:
  {
    "tests": [
      {
        "name": "suite:suite1",
        "flags": {
          "metadata": {
            "items": [
              {
                "key": "key1",
                "value": "value1"
              }
            ]
          }
        }
      },
      {
        "name": "foo_Test",
        "flags": {}
      }
    ]
  }

"flags" must strictly follow the schema of the Instance Resource
(https://cloud.google.com/compute/docs/reference/latest/instances#resource).

GCEAUWorker respects most of the properties except instance name, boot_disk,
network and zone. The enforced values of these special properties are:
  instance_name: managed name
  boot_disk: a disk with the image being verified
  network: the network that has required firewall set up
  zone: project selected default zone

Some of the properties of the Instance Resource are set by the GCE
backend so trying to set them at the client may result in noops or GCE errors,
which will be wrapped into an UpdateException.

Note that some properties like 'disks' that depend on the existence of other
resources are not supported yet.
"""

from __future__ import print_function

import datetime
import json
import os
import shutil
import time

from functools import partial
from multiprocessing import Process

from chromite.lib import cros_build_lib
from chromite.lib import cros_logging as logging
from chromite.lib import gce
from chromite.lib import gs
from chromite.lib import parallel
from chromite.lib import path_util
from chromite.lib import portage_util
from crostestutils.au_test_harness import au_worker
from crostestutils.au_test_harness import constants
from crostestutils.au_test_harness import update_exception


class GCEAUWorker(au_worker.AUWorker):
  """Test harness for updating GCE instances.

  Attributes:
    gce_context: An utility for GCE operations.
    gscontext: An utility for GCS operations.
    network: Default network to create instances in.
    machine_type: Default machine type to create instances with.
    gcs_bucket: The GCS bucket to upload image tarballs to.
    tarball_local: Local path to the tarball of test image.
    tarball_remote: GCS path to the tarball of test image.
    image: A single GCE image associated with a worker.
    image_link: The URL to the image created.
    instances: GCE VM instances associated with a worker.
    bg_delete_processes:
      Background processes that delete stale instances and images.
  """

  GS_PATH_COMMON_PREFIX = 'gs://'
  GS_URL_COMMON_PREFIX = 'https://storage.googleapis.com/'
  IMAGE_PREFIX = 'test-image-'
  INSTANCE_PREFIX = 'test-instance-'

  def __init__(self, options, test_results_root,
               project=constants.GCE_PROJECT,
               zone=constants.GCE_DEFAULT_ZONE,
               network=constants.GCE_DEFAULT_NETWORK,
               machine_type=constants.GCE_DEFAULT_MACHINE_TYPE,
               json_key_file=constants.GCE_JSON_KEY,
               gcs_bucket=constants.GCS_BUCKET):
    """Processes GCE-specific options."""
    super(GCEAUWorker, self).__init__(options, test_results_root)
    self.gce_context = gce.GceContext.ForServiceAccountThreadSafe(
        project, zone, json_key_file=json_key_file)
    self.gscontext = gs.GSContext()
    self.network = network
    self.machine_type = machine_type
    self.gcs_bucket = gcs_bucket
    self.tarball_local = None
    self.tarball_remote = None
    self.image = None
    self.image_link = None
    # One instance per test.
    self.instances = {}

    # Background processes that delete throw-away instances.
    self.bg_delete_processes = []

    # Load test specifications from <overlay>/scripts/gce_tests.json, if any.
    self._LoadTests()

  def CleanUp(self):
    """Deletes throw-away instances and images."""
    logging.info('Waiting for GCP resources to be deleted.')
    self._WaitForBackgroundDeleteProcesses()
    self._DeleteExistingResources()
    logging.info('All resources are deleted.')

  def PrepareBase(self, image_path, signed_base=False):
    """Auto-update to base image to prepare for test."""
    return self.PrepareRealBase(image_path, signed_base)

  def UpdateImage(self, image_path, src_image_path='', stateful_change='old',
                  proxy_port=None, payload_signing_key=None):
    """Updates the image on all GCE instances.

    There may be multiple instances created with different gcloud flags that
    will be used by different tests or suites.

    Unlike vm_au_worker or real_au_worker, UpdateImage always creates a new
    image and a new instance.
    """
    # Delete existing resources in the background if any.
    bg_delete = Process(target=self._DeleteExistingResources)
    bg_delete.start()
    self.bg_delete_processes.append(bg_delete)

    # Creates an image and instances.
    self._CreateImage(image_path)
    self._CreateInstances()

  def VerifyImage(self, unittest, percent_required_to_pass=100, test=''):
    """Verifies the image by running all the required tests.

    Run the test targets as specified in <overlay>/scripts/gce_gce_tests.json or
    the default 'gce-smoke' suite if none. Multiple test targets are run in
    parallel. Test results are joined and printed after all tests finish. Note
    that a dedicated instance has been created for each test target.

    Args:
      unittest: (unittest.TestCase) The test case to report results back to.
      percent_required_to_pass: (int) The required minimum pass rate. Not used.
      test: (str) The specific test to run. Not used.

    Returns:
      True if all tests pass, or False otherwise.
    """
    log_directory_base, fail_directory_base = self.GetNextResultsPath(
        'autotest_tests')

    steps = []
    for test in self.tests:
      remote = self.gce_context.GetInstanceIP(self.instances[test['name']])
      # Prefer partial to lambda because of Python's late binding.
      steps.append(partial(self._RunTest, test['name'], remote,
                           log_directory_base, fail_directory_base))
    return_values = parallel.RunParallelSteps(steps, return_values=True)

    passed = True
    outputs = {}
    for test, percent_passed, output in return_values:
      passed &= (percent_passed == 100)
      outputs[test] = output

    if not passed:
      self._HandleFail(log_directory_base, fail_directory_base)
      if unittest is not None:
        unittest.fail('Not all tests passed')
      for test, output in outputs.iteritems():
        print ('\nTest: %s\n' % test)
        print (output)
    return passed

  # --- PRIVATE HELPER FUNCTIONS ---

  def _RunTest(self, test, remote, log_directory_base, fail_directory_base):
    """Runs a test or a suite of tests on a given remote.

    Runs a test target, whether an individual test or a suite of tests, with
    'test_that'.

    Args:
      test: (str) The test or suite to run.
      remote: (str) The hostname of the remote DUT.
      log_directory_base:
          (str) The base directory to store test logs. A sub directory specific
          to this test will be created there.
      fail_directory_base:
          (str) The base directory to store test logs in case of a test failure.

    Returns:
      test:
          (str) Same as |test|. This is useful when the caller wants to
          correlate results to the test name.
      percent_passed: (int) Pass rate.
      output: (str): Original test output.
    """
    log_directory, _ = self._GetResultsDirectoryForTest(
        test, log_directory_base, fail_directory_base)
    log_directory_in_chroot = log_directory.rpartition('chroot')[2]

    cmd = ['test_that', '-b', self.board, '--no-quickmerge',
           '--results_dir=%s' % log_directory_in_chroot, remote, test]
    if self.ssh_private_key is not None:
      cmd.append('--ssh_private_key=%s' %
                 path_util.ToChrootPath(self.ssh_private_key))

      result = cros_build_lib.RunCommand(cmd, error_code_ok=True,
                                         enter_chroot=True,
                                         redirect_stdout=True,
                                         cwd=constants.CROSUTILS_DIR)
      percent_passed = self.ParseGeneratedTestOutput(result.output)
    return test, percent_passed, result.output

  def _GetResultsDirectoryForTest(self, test, log_directory_base,
                                  fail_directory_base):
    """Gets the log and fail directories for a particular test.

    Args:
      test: (str) The test or suite to get directories for.
      log_directory_base:
          (str) The base directory where all test results are saved.
      fail_directory_base:
          (str) The base directory where all test failures are recorded.
    """
    log_directory = os.path.join(log_directory_base, test)
    fail_directory = os.path.join(fail_directory_base, test)

    if not os.path.exists(log_directory):
      os.makedirs(log_directory)
    return log_directory, fail_directory

  def _LoadTests(self):
    """Loads the tests to run from <overlay>/scripts/gce_tests.json.

    If the JSON file exists, loads the tests and flags to create instance for
    each test with. The JSON file should contain a "tests" object, which is an
    array of objects, each of which has only two keys: "name" and "flags".

    "name" could be any valid Autotest test name, or a suite name, in the form
    of "suite:<suite_name>", e.g., "suite:gce-smoke".

    "flags" is a JSON object whose members must be valid proterties of the GCE
    Instance Resource, as specificed at:
    https://cloud.google.com/compute/docs/reference/latest/instances#resource.

    These flags will be used to create instances. Each flag must strictly follow
    the property schema as defined in the Instance Resource. Failure to do so
    will result in instance creation failures.

    Note that a dedicated instance will be created for every test object
    specified in scripts/gce_tests.json. So group test cases that require
    similar instance properties together as suites whenever possible.

    An example scripts/gce_tests.json may look like:
    {
      "tests": [
        {
          "name": "suite:gce-smoke",
          "flags": []
        },
        {
          "name": "suite:cloud-init",
          "flags": {
              "description": "Test instance",
              "metadata": {
                "items": [
                  {
                    "key": "fake_key",
                    "value": "fake_value"
                  }
                ]
              }
          }
        }
      ]
    }

    If the JSON file does not exist, the 'gce-smoke' suite will be used to
    verify the image.
    """
    # Defaults to run the gce-smoke suite if no custom tests are given.
    tests = [dict(name="suite:gce-smoke", flags=dict())]

    custom_tests = None
    try:
      custom_tests = portage_util.ReadOverlayFile(
          'scripts/gce_tests.json', board=self.board)
    except portage_util.MissingOverlayException as e:
      logging.warn('Board overlay not found. Error: %r', e)

    if custom_tests is not None:
      if self.board not in constants.TRUSTED_BOARDS:
        logging.warn('Custom tests and flags are not allowed for this board '
                     '(%s)!', self.board)
      else:
        # Read the list of tests.
        try:
          json_file = json.loads(custom_tests)
          tests = json_file.get('tests')
        except ValueError as e:
          logging.warn('scripts/gce_tests.json contains invalid JSON content. '
                       'Default tests will be run and default flags will be '
                       'used to create instances. Error: %r', e)
    self.tests = tests

  def _CreateImage(self, image_path):
    """Uploads the gce tarball and creates an image with it."""
    log_directory, fail_directory = self.GetNextResultsPath('update')

    ts = datetime.datetime.fromtimestamp(time.time()).strftime(
        '%Y-%m-%d-%H-%M-%S')

    # Upload the GCE tarball to Google Cloud Storage.
    self.tarball_local = image_path
    gs_directory = ('gs://%s/%s' % (self.gcs_bucket, ts))
    try:
      self.gscontext.CopyInto(self.tarball_local, gs_directory)
      self.tarball_remote = '%s/%s' % (gs_directory,
                                       os.path.basename(self.tarball_local))
    except Exception as e:
      raise update_exception.UpdateException(
          1, 'Update failed. Unable to upload test image GCE tarball to GCS. '
          'Error: %s' % e)

    # Create an image from |image_path| and an instance from the image.
    image = '%s%s' % (self.IMAGE_PREFIX, ts)
    try:
      self.image_link = self.gce_context.CreateImage(
          image, self._GsPathToUrl(self.tarball_remote))
      self.image = image
    except gce.Error as e:
      self._HandleFail(log_directory, fail_directory)
      raise update_exception.UpdateException(1, 'Update failed. Error: %r' % e)

  def _CreateInstances(self):
    """Creates instances with custom flags as specificed in |self.tests|."""
    steps = []
    for test in self.tests:
      ts = datetime.datetime.fromtimestamp(time.time()).strftime(
          '%Y-%m-%d-%H-%M-%S')
      instance = '%s%s' % (self.INSTANCE_PREFIX, ts)
      kwargs = test['flags'].copy()
      kwargs['description'] = 'For test %s' % test['name']
      steps.append(partial(self.gce_context.CreateInstance, instance,
                           self.image_link, network=self.network,
                           machine_type=self.machine_type, **kwargs))
      self.instances[test['name']] = instance
    parallel.RunParallelSteps(steps)

  def _DeleteExistingResouce(self, resource, existence_checker, deletor):
    """Deletes a resource if it exists.

    This method checks the existence of a resource using |existence_checker|,
    and deletes it on true.

    Args:
      resource: (str) The resource name/url to delete.
      existence_checker:
        (callable) The callable to check existence. This callable should take
        |resource| as its first argument.
      deletor:
        (callable) The callable to perform the deletion. This callable should
        take |resource| as its first argument.

    Raises:
      ValueError if existence_checker or deletor is not callable.
    """
    if not hasattr(existence_checker, '__call__'):
      raise ValueError('existence_checker must be a callable')
    if not hasattr(deletor, '__call__'):
      raise ValueError('deletor must be a callable')

    if existence_checker(resource):
      deletor(resource)

  def _DeleteExistingResources(self):
    """Delete instances, image and the tarball on GCS if they exist."""
    steps = []

    if self.tarball_remote:
      steps.append(partial(self.gscontext.DoCommand,
                           ['rm', self.tarball_remote]))
    if self.image:
      steps.append(partial(self.gce_context.DeleteImage, self.image))

    for instance in self.instances.values():
      steps.append(partial(
          self._DeleteExistingResouce,
          resource=instance,
          existence_checker=self.gce_context.InstanceExists,
          deletor=self.gce_context.DeleteInstance))

    # Delete all resources in parallel.
    try:
      parallel.RunParallelSteps(steps)
    except Exception as e:
      logging.warn('Infrastructure failure. Error: %r' % e)

    # Reset variables.
    self.tarball_remote = None
    self.image = None
    self.image_link = None
    self.instances = {}

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

    self._DeleteExistingResources()

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

  def _WaitForBackgroundDeleteProcesses(self):
    """Waits for all background proecesses to finish."""
    for p in self.bg_delete_processes:
      p.join()
    self.bg_delete_processes = []
