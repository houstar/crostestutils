#!/usr/bin/python

# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Stress test for dev_server_wrapper.

Test script runs forever stressing the ability to start and stop the
dev_server_wrapper. Even very rare hangs will cause significant build flake.
"""

import sys

import constants
sys.path.append(constants.CROSUTILS_LIB_DIR)
sys.path.append(constants.CROS_PLATFORM_ROOT)
sys.path.append(constants.SOURCE_ROOT)

from crostestutils.lib import dev_server_wrapper

i = 0
while True:
  i += 1
  print 'Iteration {}'.format(i)
  wrapper = dev_server_wrapper.DevServerWrapper('/tmp')
  print 'Starting'
  wrapper.start()
  print 'Waiting for Started'
  wrapper.WaitUntilStarted()
  print 'Stopping'
  wrapper.Stop()
