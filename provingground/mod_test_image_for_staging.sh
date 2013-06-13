#!/bin/bash

# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Description:
# Script modifies a chromiumos image so that it will work with test
# instances of the DM Server and GAIA in the staging environment.
#
# When run, the script will mount the specified image, update the
# session_manager_setup.sh file, and then re-sign the image with devkey.
#

. "/usr/lib/crosutils/common.sh" || { echo "Unable to load common.sh"; exit 1; }

assert_inside_chroot

DEFINE_string dmserver \
  "https://cros-dev.sandbox.google.com/devicemanagement/data/api" \
  "Complete URL for the DM Server" d
DEFINE_string gaiaserver "https://gaiastaging.corp.google.com" \
  "Complete URL for the GAIA server" g
DEFINE_string image "$FLAGS_image" \
  "Path and name of the chromiumos image file" i

# Parse command line.
FLAGS "$@" || exit 1
eval set -- "$FLAGS_ARGV"

set -e

FLAGS_image=$(eval readlink -f "${FLAGS_image}")
IMAGE_DIR=$(dirname "${FLAGS_image}")
IMAGE_NAME=$(basename "${FLAGS_image}")
ROOT_FS_DIR="${IMAGE_DIR}/rootfs"
SMS_FILE="${ROOT_FS_DIR}/sbin/session_manager_setup.sh"
DEVKEYS_DIR="/usr/share/vboot/devkeys"
VBOOT_DIR="${CHROOT_TRUNK_DIR}/src/platform/vboot_reference/scripts/"\
"image_signing"

NL="\\\\\n"
PAD="            "
ARGS="${PAD}--gaia-url=${FLAGS_gaiaserver} ${NL}"\
"${PAD}--lso-url=https://test-sandbox.auth.corp.google.com ${NL}"\
"${PAD}--google-apis-host=www-googleapis-test.sandbox.google.com ${NL}"\
"${PAD}--oauth2-client-id=236834563817.apps.googleusercontent.com ${NL}"\
"${PAD}--oauth2-client-secret=RsKv5AwFKSzNgE0yjnurkPVI ${NL}"\
"${PAD}--ignore-urlfetcher-cert-requests \\\\"

cleanUp() {
  "${SCRIPTS_DIR}/mount_gpt_image.sh" -u -r "$ROOT_FS_DIR"
}

if [ ! -d "$VBOOT_DIR" ]; then
  die "The required path: $VBOOT_DIR does not exist. This directory needs"\
      "to be sync'd into your chroot.\n $ cros_workon start vboot_reference"
fi

trap cleanUp EXIT

# Mount gpt (GUID partition table) image, and sets up var, /usr/local,
# and symlinks.
"$SCRIPTS_DIR/mount_gpt_image.sh" --image="$IMAGE_NAME" --from="$IMAGE_DIR" \
  --rootfs_mountpt="$ROOT_FS_DIR"

# Create backup of session manager setup file.
sudo cp ${SMS_FILE} ${SMS_FILE}.bak

# Update DMSERVER to user-specified URI.
sudo sed -i 's@^DMSERVER=.*@DMSERVER="'${FLAGS_dmserver}'"@' ${SMS_FILE}

# Insert Staging Server arguments.
sudo sed -i '/--device-management-url/i\'"${ARGS}"'' ${SMS_FILE}

trap - EXIT

cleanUp

TMP_BIN_PATH="${FLAGS_image}.new"
"${VBOOT_DIR}/sign_official_build.sh" usb "${FLAGS_image}" \
                                     "${DEVKEYS_DIR}" \
                                     "${TMP_BIN_PATH}"

echo "Renaming from ${TMP_BIN_PATH} to ${FLAGS_image}."
mv "${TMP_BIN_PATH}" "${FLAGS_image}"
