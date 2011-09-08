#!/bin/bash

# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Script to setup environment variables so that cros_gestures cli can
# find .boto files for authentication and related gsutil files.

declare GSUTIL_BASE="$HOME/gsutil"
declare SRC_BASE="$HOME/cros"
declare TESTBOTO=\
"${SRC_BASE}/src/third_party/autotest-private/cros_gestures_boto"
declare AUTOTEST_SRC="${SRC_BASE}/src/third_party/autotest/files"

function check_and_set_var() {
  local var_name=$1
  local var_value=$2
  local dir_or_file=$3
  if [[ ${dir_or_file} == dir && -d "${var_value}" ]] || \
     [[ ${dir_or_file} == file && -f "${var_value}" ]]; then
    echo Setting ${var_name}
    export ${var_name}="${var_value}"
    echo -e "\tto ${var_value}."
  fi
}

echo ---------------------------------------------------------------------
check_and_set_var GSUTIL_BIN_DIR ${GSUTIL_BASE} dir
check_and_set_var BOTO_CONFIG \
    ${TESTBOTO}/trusted_dev/chromeos.gestures.trusted.write.boto file
check_and_set_var BOTO_VALIDATE_CONFIG \
    ${TESTBOTO}/validator/chromeos.gestures.full.boto file
check_and_set_var TRACKPAD_TEST_DIR \
    ${AUTOTEST_SRC}/client/site_tests/hardware_Trackpad dir
echo Done.
echo ---------------------------------------------------------------------
echo "Do not forget to run this as . ./setup_cros_gestures.sh"
echo ---------------------------------------------------------------------
