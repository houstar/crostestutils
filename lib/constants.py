# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

_TEST_LIB_PATH = os.path.realpath(__file__)

CROS_PLATFORM_ROOT = os.path.join(os.path.dirname(_TEST_LIB_PATH), '..', '..')

SOURCE_ROOT = os.path.join(
    os.path.dirname(_TEST_LIB_PATH), '..', '..', '..', '..')

CROSUTILS_LIB_DIR = os.path.join(SOURCE_ROOT, 'src/scripts/lib')
