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

declare -i PREFLIGHT_POOL_VERSION=41

if [[ $# -eq 0  ||  -z $2 ]] ; then
  echo $USAGE_STRING
  exit
fi

# atheros_ar9300 on kernel 3.4
list_1=(alex lumpy stumpy)

# atheros_ar9462 on kernel 3.4
list_2=(parrot butterfly)

# atheros_ar9462 on kernel 3.8
list_3=(link stout peppy falco monroe panther leon wolf mccloud zako)

# marvell_88w8797_2x2 on kernel 3.8
list_4=(snow spring skate)

# marvell_88w8897_2x2 on kernel 3.8
list_5=(peach_pi peach_pit)

# marvell_88w8897_2x2 on kernel 3.10
list_6=(nyan_big nyan_blaze)

# intel wilkins peak 2 on kernel 3.8
list_7=(falco_li tricky)

# intel wilkins peak 2 on kernel 3.10
list_8=(squawks expresso clapper glimmer quawks enguarde kip squawks gnawty
        swanky winky candy)

# intel wilkins peak 2 on kernel 3.14
list_9=(samus auron_paine auron_yuna)

# wificell_preflight boards; leaving empty for future boards
# Marvell 8897 and Broadcom on kernel 3.10
list_10=(glimmer)

DESIRED_BOARDS=(list_1 list_2 list_3 list_4 list_5 list_6 list_7 list_8 list_9)

if [ $BRANCH -ge ${PREFLIGHT_POOL_VERSION} ] ; then
  DESIRED_BOARDS+=(list_10)
fi

# POOLS format: POOLS[<pool name>]=<suite name>
declare -A POOLS
POOLS[wificell]=wifi_release
POOLS[wificell_preflight]=wifi_release

return_item_exists_in_array() {
  for current_board in ${boards_to_run[@]}; do
    if [[ ${1} == ${current_board} ]] ; then
      echo 'True'
    fi
  done;
  echo 'False'
}

return_available_hosts() {
  OIFS='$IFS'
  IFS=$'\n'

  boards=("${!1}")
  local pool=${2}

  #TODO: Filter out stderr so the user doesn't see it.
  for host in `$ATEST host list | grep -w 'pool:'${2}` ; do
    IFS=$' '
    local host_info=($host)
    for board in ${boards[@]}; do
      if [[ $board == ${host_info[4]} && (${host_info[1]} != 'Repairing' &&
        ${host_info[1]} != 'Repair Failed') &&
        ${host_info[3]} == 'False' ]] ; then
        already_added=$(return_item_exists_in_array ${board})
        if [[ ${already_added} == 'False' ]] ; then
          boards_to_run+=($board)
        fi
      fi
    done;
    IFS=$'\n'
  done;
  IFS=$OIFS
}

return_host_list() {
  local pool=${1}
  for sub_list in ${DESIRED_BOARDS[@]} ; do
    previous_count=${#boards_to_run[@]}

    subst="$sub_list[@]"
    list_items=(`echo "${!subst}"`)
    return_available_hosts list_items[@] ${pool}

    current_count=${#boards_to_run[@]}
    if [ $current_count -eq $previous_count ] ; then
      echo 'No devices from '$sub_list' ('${list_items}') were available!'
    fi

  done;
}

results_folder='/tmp/connectivity_release_'
results_folder+=$BRANCH'-'$BUILD'-'`date +%Y-%m-%d-%H-%M-%S`
if [ -e ${results_folder} ] ; then
  rm -rf ${results_folder}
fi

mkdir $results_folder
latest_results_folder='/tmp/connectivity_results_latest'
if [ -h ${latest_results_folder} ] ; then
  rm -rf ${latest_results_folder}
fi
ln -s ${results_folder} ${latest_results_folder}

for pool in "${!POOLS[@]}"; do
  boards_to_run=()
  return_host_list ${pool}

  for board in ${boards_to_run[@]}; do
    # Perform the conversion from autotest platform names to board build names
    if [ $board == 'spring' ] ; then
      board='daisy_spring'
    elif [ $board == 'skate' ] ; then
      board='daisy_skate'
    elif [ $board == 'snow' ] ; then
      board='daisy'
    elif [ $board == 'alex' ] ; then
      board='x86-alex'
    fi

    run_command=$RUN_SUITE' --build='$board'-release/R'$BRANCH'-'$BUILD
    run_command+=' --pool='$pool' --board='$board' --suite_name='${POOLS[$pool]}

    results_file=$results_folder'/'$pool'_'$board'.txt'

    eval $run_command &> $results_file &
    disown %1

  done;
done;

echo 'All results are available in: '${results_folder}
