# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

_TEST_LIB_PATH = os.path.realpath(__file__)

CROS_PLATFORM_ROOT = os.path.join(os.path.dirname(_TEST_LIB_PATH), '..', '..')

DEFAULT_CHROOT_DIR = 'chroot'

SOURCE_ROOT = os.path.realpath(os.path.join(
    os.path.dirname(_TEST_LIB_PATH), '..', '..', '..', '..'))

CROSUTILS_DIR = os.path.join(SOURCE_ROOT, 'src', 'scripts')

CROSUTILS_LIB_DIR = os.path.join(CROSUTILS_DIR, 'lib')

MAX_TIMEOUT_SECONDS = 4800

# Information of the GCE autotest bots.
GCE_PROJECT = 'cros-autotest-bots'
GCE_DEFAULT_ZONE = 'us-central1-a'
GCE_DEFAULT_NETWORK = 'network-prod'
GCE_DEFAULT_MACHINE_TYPE = 'n1-standard-8'
GCE_JSON_KEY = '/creds/service_accounts/service-account-cros-autotest-bots.json'
GCS_BUCKET = 'chromeos-test-gce-tarballs'

TRUSTED_BOARDS = [
    'lakitu'
]
