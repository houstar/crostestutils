#!/bin/bash

# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

set -e

BRANCH=$1
BUILD=$2

ATEST='../../../third_party/autotest/files/cli/atest'
RUN_SUITE='../../../third_party/autotest/files/site_utils/run_suite.py'

USAGE_STRING='Usage: ./run_wifi_release_suite.sh <branch number> <build number>'

if [[ $# -eq 0  ||  -z $2 ]] ; then
  echo $USAGE_STRING
  exit
fi

# atheros_ar9300 on kernel 3.4
list_1=(alex lumpy stumpy)

# atheros_ar9462 on kernel 3.4
list_2=(parrot butterfly)

# atheros_ar9462 on kernel 3.8
list_3=(link stout peppy falco)

# marvell_88w8797_2x2 on kernel 3.8
list_4=(snow spring)

DESIRED_BOARDS=(list_1 list_2 list_3 list_4)

return_available_hosts() {
  OIFS='$IFS'
  IFS=$'\n'

  boards=("${!1}")

  #TODO: Filter out stderr so the user doesn't see it.
  for host in `$ATEST host list | grep wificell` ; do
    IFS=$' '
    local host_info=($host)
    for board in ${boards[@]}; do
      if [[ $board == ${host_info[3]} && ${host_info[1]} == 'Ready' ]] ; then
        boards_to_run+=($board)
      fi
    done;
    IFS=$'\n'
  done;
  IFS=$OIFS
}

boards_to_run=()

for sub_list in ${DESIRED_BOARDS[@]} ; do
  previous_count=${#boards_to_run[@]}

  subst="$sub_list[@]"
  list_items=(`echo "${!subst}"`)
  return_available_hosts list_items[@]

  current_count=${#boards_to_run[@]}
  if [ $current_count -eq $previous_count ] ; then
    echo 'No devices from '$sub_list' were available!'
  fi

done;

#TODO: Remove duplicates from the list of boards_to_run

results_folder='/tmp/wifi_release_R'$BRANCH'-'$BUILD'-'`date +%Y-%m-%d-%H-%M-%S`
if [ -e $results_folder ] ; then
  rm -rf $results_folder
fi

#TODO: Create a wifi_release_Rx-x.latest symn link
mkdir $results_folder

for board in ${boards_to_run[@]}; do
  # Perform the conversion from autotest platform names to board build names
  if [ $board == 'spring' ] ; then
    board='daisy_spring'
  elif [ $board == 'snow' ] ; then
    board='daisy'
  elif [ $board == 'alex' ] ; then
    board='x86-alex'
  fi

  run_command=$RUN_SUITE' --build='$board'-release/R'$BRANCH'-'$BUILD
  run_command+=' --pool=wificell --board='$board' --suite_name=wifi_release'

  results_file=$results_folder'/'$board'.txt'

  echo 'Running: '$board
  eval $run_command &> $results_file &
  disown %1

done;

echo 'Results can be seen in: '$results_folder
