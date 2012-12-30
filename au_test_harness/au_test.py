# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing a test suite that is run to test auto updates."""

import os
import re
import time
import unittest
import urllib

from chromite.lib import cros_build_lib
from crostestutils.au_test_harness import cros_test_proxy
from crostestutils.au_test_harness import real_au_worker
from crostestutils.au_test_harness import update_exception
from crostestutils.au_test_harness import vm_au_worker


class AUTest(unittest.TestCase):
  """Test harness that uses an au_worker to perform and validate updates.

  Defines a test suite that is run using an au_worker.  An au_worker can
  be created to perform and validates updates on both virtual and real devices.
  See documentation for au_worker for more information.
  """

  @classmethod
  def ProcessOptions(cls, options):
    """Processes options for the test suite and sets up the worker class.

    Args:
      options: options class to be parsed from main class.
    """
    cls.base_image_path = options.base_image
    cls.private_key = options.private_key
    cls.target_image_path = options.target_image
    cls.test_results_root = options.test_results_root
    if options.type == 'vm':
      cls.worker_class = vm_au_worker.VMAUWorker
    else:
      cls.worker_class = real_au_worker.RealAUWorker

    # Cache away options to instantiate workers later.
    cls.options = options

  def AttemptUpdateWithPayloadExpectedFailure(self, payload, expected_msg):
    """Attempt a payload update, expect it to fail with expected log."""
    try:
      self.worker.UpdateUsingPayload(payload)
    except update_exception.UpdateException as err:
      # Will raise ValueError if expected is not found.
      if re.search(re.escape(expected_msg), err.output, re.MULTILINE):
        return
      cros_build_lib.Warning("Didn't find %r in:\n%s", expected_msg, err.output)

    self.fail('We managed to update when failure was expected')

  def AttemptUpdateWithFilter(self, update_filter, proxy_port=8081):
    """Update through a proxy, with a specified filter, and expect success."""
    self.worker.PrepareBase(self.target_image_path)

    # The devserver runs at port 8080 by default. We assume that here, and
    # start our proxy at a different one. We then tell our update tools to
    # have the client connect to our proxy_port instead of 8080.
    proxy = cros_test_proxy.CrosTestProxy(port_in=proxy_port,
                                          address_out='127.0.0.1',
                                          port_out=8080,
                                          filter=update_filter)
    proxy.serve_forever_in_thread()
    try:
      self.worker.PerformUpdate(self.target_image_path, self.target_image_path,
                                proxy_port=proxy_port)
    finally:
      proxy.shutdown()

  # --- UNITTEST SPECIFIC METHODS ---

  def setUp(self):
    """Overrides unittest.TestCase.setUp and called before every test.

    Sets instance specific variables and initializes worker.
    """
    super(AUTest, self).setUp()
    self.worker = self.worker_class(self.options, AUTest.test_results_root)
    self.download_folder = os.path.join(os.path.realpath(os.path.curdir),
                                        'latest_download')

  def tearDown(self):
    """Overrides unittest.TestCase.tearDown and called after every test."""
    self.worker.CleanUp()

  def testUpdateKeepStateful(self):
    """Tests if we can update normally.

    This test checks that we can update by updating the stateful partition
    rather than wiping it.
    """
    self.worker.Initialize(9222)
    # Just make sure some tests pass on original image.  Some old images
    # don't pass many tests.
    self.worker.PrepareBase(self.base_image_path)

    # Update to
    self.worker.PerformUpdate(self.target_image_path, self.base_image_path)
    self.assertTrue(self.worker.VerifyImage())

    # Update from
    self.worker.PerformUpdate(self.target_image_path, self.target_image_path)
    self.assertTrue(self.worker.VerifyImage())

  def testUpdateWipeStateful(self):
    """Tests if we can update after cleaning the stateful partition.

    This test checks that we can update successfully after wiping the
    stateful partition.
    """
    self.worker.Initialize(9223)
    # Just make sure some tests pass on original image.  Some old images
    # don't pass many tests.
    self.worker.PrepareBase(self.base_image_path)

    # Update to
    self.worker.PerformUpdate(self.target_image_path, self.base_image_path,
                              'clean')
    self.assertTrue(self.worker.VerifyImage())

    # Update from
    self.worker.PerformUpdate(self.target_image_path, self.target_image_path,
                              'clean')
    self.assertTrue(self.worker.VerifyImage())

  def testInterruptedUpdate(self):
    """Tests what happens if we interrupt payload delivery 3 times."""

    class InterruptionFilter(cros_test_proxy.Filter):
      """This filter causes the proxy to interrupt the download 3 times.

      It does this by closing the first three connections after they transfer
      2M total in the outbound direction.
      """

      def __init__(self):
        """Defines variable shared across all connections."""
        self.close_count = 0

      def setup(self):
        """Called once at the start of each connection."""
        self.data_size = 0

      # Overriden method.  The first three connections transferring more than 2M
      # outbound will be closed.
      def OutBound(self, data):
        if self.close_count < 3:
          if self.data_size > (2 * 1024 * 1024):
            self.close_count += 1
            return None

        self.data_size += len(data)
        return data

    self.worker.Initialize(9224)
    self.AttemptUpdateWithFilter(InterruptionFilter(), proxy_port=8082)

  def testSimpleSignedUpdate(self):
    """Test that updates to itself with a signed payload."""
    self.worker.Initialize(9226)
    self.worker.PrepareBase(self.target_image_path, signed_base=True)
    if self.private_key:
      self.worker.PerformUpdate(self.target_image_path,
                                self.target_image_path + '.signed',
                                private_key_path=self.private_key)
    else:
      cros_build_lib.Info('No key found to use for signed testing.')

  def SimpleTestUpdateAndVerify(self):
    """Test that updates to itself.

    We explicitly don't use test prefix so that isn't run by default.  Can be
    run using test_prefix option.
    """
    self.worker.Initialize(9227)
    self.worker.PrepareBase(self.target_image_path)
    self.worker.PerformUpdate(self.target_image_path, self.target_image_path)
    self.assertTrue(self.worker.VerifyImage())

  def SimpleTestVerify(self):
    """Test that only verifies the target image.

    We explicitly don't use test prefix so that isn't run by default.  Can be
    run using test_prefix option.
    """
    self.worker.Initialize(9228)
    self.worker.PrepareBase(self.target_image_path)
    self.assertTrue(self.worker.VerifyImage())

  # --- DISABLED TESTS ---

  def NoTestDelayedUpdate(self):
    """Tests what happens if some data is delayed during update delivery."""

    class DelayedFilter(cros_test_proxy.Filter):
      """Causes intermittent delays in data transmission.

      It does this by inserting 3 20 second delays when transmitting
      data after 2M has been sent.
      """

      def setup(self):
        """Called once at the start of each connection."""
        self.data_size = 0
        self.delay_count = 0

      # The first three packets after we reach 2M transferred
      # are delayed by 20 seconds.
      def OutBound(self, data):
        if self.delay_count < 3:
          if self.data_size > (2 * 1024 * 1024):
            self.delay_count += 1
            time.sleep(20)

        self.data_size += len(data)
        return data

    self.worker.Initialize(9225)
    self.AttemptUpdateWithFilter(DelayedFilter(), proxy_port=8083)

  def NotestPlatformToolchainOptions(self):
    """Tests the hardened toolchain options."""
    self.worker.Initialize(9229)
    self.worker.PrepareBase(self.base_image_path)
    self.assertTrue(self.worker.VerifyImage('platform_ToolchainOptions'))

  # TODO(sosa): Get test to work with verbose.
  def NotestPartialUpdate(self):
    """Tests what happens if we attempt to update with a truncated payload."""
    self.worker.Initialize(9230)
    # Preload with the version we are trying to test.
    self.worker.PrepareBase(self.target_image_path)

    # Image can be updated at:
    # ~chrome-eng/chromeos/localmirror/autest-images
    url = ('http://gsdview.appspot.com/chromeos-localmirror/'
           'autest-images/truncated_image.gz')
    payload = os.path.join(self.download_folder, 'truncated_image.gz')

    # Read from the URL and write to the local file
    urllib.urlretrieve(url, payload)

    expected_msg = 'download_hash_data == update_check_response_hash failed'
    self.AttemptUpdateWithPayloadExpectedFailure(payload, expected_msg)

  # TODO(sosa): Get test to work with verbose.
  def NotestCorruptedUpdate(self):
    """Tests what happens if we attempt to update with a corrupted payload."""
    self.worker.Initialize(9231)
    # Preload with the version we are trying to test.
    self.worker.PrepareBase(self.target_image_path)

    # Image can be updated at:
    # ~chrome-eng/chromeos/localmirror/autest-images
    url = ('http://gsdview.appspot.com/chromeos-localmirror/'
           'autest-images/corrupted_image.gz')
    payload = os.path.join(self.download_folder, 'corrupted.gz')

    # Read from the URL and write to the local file
    urllib.urlretrieve(url, payload)

    # This update is expected to fail...
    expected_msg = 'zlib inflate() error:-3'
    self.AttemptUpdateWithPayloadExpectedFailure(payload, expected_msg)
