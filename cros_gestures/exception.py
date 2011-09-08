#!/usr/bin/python
# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Custom exceeptions for ChromeOS Gestures command line interface.

This code is modeled after and derived from the Command class in
gsutil/gslib/command.py.
"""

class CrosGesturesException(StandardError):
  """Exception raised when a problem is encountered running a gsutil command.

  This exception should be used to signal user errors or system failures
  (like timeouts), not bugs (like an incorrect param value). For the
  latter you should raise Exception so we can see where/how it happened
  via gsutil -D (which will include a stack trace for raised Exceptions).
  """
  def __init__(self, reason, informational=False):
    """Instantiate a CrosGesturesException.

    Args:
      reason: text describing the problem.
      informational: indicates reason should be printed as FYI, not a failure.
    """
    StandardError.__init__(self)
    self.reason = reason
    self.informational = informational

  def __repr__(self):
    return 'CrosGesturesException: %s' % self.reason

  def __str__(self):
    return 'CrosGesturesException: %s' % self.reason
