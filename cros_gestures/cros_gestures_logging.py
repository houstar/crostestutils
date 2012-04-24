#!/usr/bin/python
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Logging optinos to support cros_gestures

Setup logging options and global debug variable used by underlying
gsutil and boto libraries.
"""

import logging
import sys

import cros_gestures_constants


class NoLoggingFilter(logging.Filter):
  """Used to filter logging messages. This completely blocks messages."""
  def filter(self, record):
    return False


def SetupLogging(options):
  """Initialize logging options."""

  if options.detaileddebugout or options.debugout:
    logging_level = logging.DEBUG
    if options.detaileddebugout:
      cros_gestures_constants.debug = 3  # from gsutil show httplib headers
    else:
      cros_gestures_constants.debug = 2  # from gsutil
  else:
    logging_level = logging.INFO
    # Mute verbose oauth logging.
    oauth_log = logging.getLogger('oauth2_client')
    oauth_log.addFilter(NoLoggingFilter())

  logging.basicConfig(level=logging_level)
