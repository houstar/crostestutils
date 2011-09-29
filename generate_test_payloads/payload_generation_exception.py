# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing payload generation exception."""


class PayloadGenerationException(Exception):
  """Exception thrown when we fail to create an update payload."""
  pass
