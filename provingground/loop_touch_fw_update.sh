#!/bin/bash

# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Script to run on a test image DUT (HOST) and test firmware updates.
# Supply a build with one firmware (FROM_BUILD) and a build with a second
# (TO_BUILD).  This script will install the first, check the firmware, install
# the second, check the firmware, repeat.

USAGE_STRING='loop_touch_fw_update.sh HOST FROM_BUILD TO_BUILD COUNT(OPTIONAL)'
# HOST: IP of DUT
# FROM_BUILD: path to .bin file of older test image
# TO_BUILD: path to .bin file for newer test image
# COUNT: number of times to loop the test (default 50)

# Test Setup
ERRORS_FOUND=0
i=0

if [ -z "$1" ] ||  [ -z "$2" ] || [ -z "$3" ]
then
  echo "Required inputs HOST, FROM_BUILD, and/or TO_BUILD not set!"
  echo $USAGE_STRING
  exit 1
fi
HOST="$1"
FROM_BUILD="$2"
TO_BUILD="$3"

if ! [ -f "$FROM_BUILD" ] || ! [ -f "$TO_BUILD" ]
then
  echo "$FROM_BUILD and/or $TO_BUILD do not exist!"
  exit 1
fi

if [ -z "$4" ]
then
  LIMIT=50
else
  LIMIT="$4"
fi

echo "Running touch_update test script."
echo "HOST: $HOST"
echo "FROM_BUILD: $FROM_BUILD"
echo "TO_BUILD: $TO_BUILD"
echo "COUNT: $LIMIT"


function check_firmware {
  # Run touch update autotest and check for pass/fail.
  test_that $HOST --board=link touch_UpdateErrors
  count=`grep "FAIL" /tmp/test_that_latest/results*/status* | wc -l`
  if [ $count -gt 0 ]
  then
    ERRORS_FOUND=$((ERRORS_FOUND+1))
    echo "Found errors!"
    grep "touch-firmware" /tmp/test_that_latest/results*/sysinfo/messages
  else
    echo "No problems found during touch firmware update."
  fi
}

function load_build {
  # Run cros flash to apply the next build to the DUT.
  echo "FLASHING "$nextbuild
  cros flash $HOST $nextbuild
}


echo "Starting Test!"
while [ $ERRORS_FOUND -eq 0 ] && [ $i -lt $LIMIT ]
do
  echo "LOOP "$i":"
  i=$((i+1))
  nextbuild=$FROM_BUILD
  load_build
  check_firmware
  nextbuild=$TO_BUILD
  load_build
  check_firmware
done

if [ $ERRORS_FOUND -gt 0 ]
then
  echo "Found ERROR after $i tries!"
else
  echo "Completed test.  No problems found."
fi
