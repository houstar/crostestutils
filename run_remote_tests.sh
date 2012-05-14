#!/bin/bash

# Copyright (c) 2009 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This can only run inside the chroot.
CROSUTILS=/usr/lib/crosutils
. "${CROSUTILS}/common.sh" || exit 1
. "${CROSUTILS}/remote_access.sh" || die "Unable to load remote_access.sh"

DEFINE_string args "" \
    "Command line arguments for test. Quoted and space separated if multiple." a
DEFINE_string autotest_dir "" \
    "Skip autodetection of autotest and use the specified location (must be in \
chroot)."
DEFINE_string board "" \
    "The board for which you are building autotest"
DEFINE_boolean build ${FLAGS_FALSE} "Build tests while running" b
DEFINE_boolean cleanup ${FLAGS_FALSE} "Clean up temp directory"
DEFINE_integer iterations 1 "Iterations to run every top level test" i
# These are passed directly so if strings are to be passed they need to be
# quoted with \". Example --profiler_args="options=\"hello\"".
DEFINE_string profiler_args "" \
    "Arguments to pass to the profiler."
DEFINE_string profiler "" \
    "The name of the profiler to use. Ex: cros_perf, pgo, etc."
DEFINE_string results_dir_root "" "alternate root results directory"
DEFINE_string update_url "" "Full url of an update image."
DEFINE_boolean use_emerged ${FLAGS_FALSE} \
    "Force use of emerged autotest packages"
DEFINE_integer verbose 1 "{0,1,2} Max verbosity shows autoserv debug output." v
DEFINE_boolean whitelist_chrome_crashes ${FLAGS_FALSE} \
    "Treat Chrome crashes as non-fatal."

# The prefix to look for in an argument that determines we're talking about a
# new-style suite.
SUITES_PREFIX='suite:'
FLAGS_HELP="
Usage: $0 --remote=[hostname] [[test...] ..]:
Each 'test' argument either has a '${SUITES_PREFIX}' prefix to specify a suite
or a regexp pattern that must uniquely match a control file.
For example:
  $0 --remote=MyMachine BootPerfServer suite:bvt"

RAN_ANY_TESTS=${FLAGS_FALSE}

stop_ssh_agent() {
  # Call this function from the exit trap of the main script.
  # Iff we started ssh-agent, be nice and clean it up.
  # Note, only works if called from the main script - no subshells.
  if [[ 1 -eq ${OWN_SSH_AGENT} ]]; then
    kill ${SSH_AGENT_PID} 2>/dev/null
    unset OWN_SSH_AGENT SSH_AGENT_PID SSH_AUTH_SOCK
  fi
}

start_ssh_agent() {
  local tmp_private_key=$TMP/autotest_key
  if [ -z "$SSH_AGENT_PID" ]; then
    eval $(ssh-agent)
    OWN_SSH_AGENT=1
  else
    OWN_SSH_AGENT=0
  fi
  cp $FLAGS_private_key $tmp_private_key
  chmod 0400 $tmp_private_key
  ssh-add $tmp_private_key
}

cleanup() {
  # Always remove the build path in case it was used.
  [[ -n "${BUILD_DIR}" ]] && sudo rm -rf "${BUILD_DIR}"
  if [[ $FLAGS_cleanup -eq ${FLAGS_TRUE} ]] || \
     [[ ${RAN_ANY_TESTS} -eq ${FLAGS_FALSE} ]]; then
    rm -rf "${TMP}"
  else
    ln -nsf "${TMP}" /tmp/run_remote_tests.latest ||
        warn "Could not link latest test directory."
    echo ">>> Details stored under ${TMP}"
  fi
  stop_ssh_agent
  cleanup_remote_access
}

# Determine if a control is for a client or server test.  Echos
# either "server" or "client".
# Arguments:
#   $1 - control file path
read_test_type() {
  local control_file=$1
  # Assume a line starts with TEST_TYPE =
  local test_type=$(egrep -m1 \
                    '^[[:space:]]*TEST_TYPE[[:space:]]*=' "${control_file}")
  if [[ -z "${test_type}" ]]; then
    die "Unable to find TEST_TYPE line in ${control_file}"
  fi
  test_type=$(python -c "${test_type}; print TEST_TYPE.lower()")
  if [[ "${test_type}" != "client" ]] && [[ "${test_type}" != "server" ]]; then
    die "Unknown type of test (${test_type}) in ${control_file}"
  fi
  echo ${test_type}
}

create_tmp() {
  # Set global TMP for remote_access.sh's sake
  # and if --results_dir_root is specified,
  # set TMP and create dir appropriately
  if [[ -n "${FLAGS_results_dir_root}" ]]; then
    TMP=${FLAGS_results_dir_root}
    mkdir -p -m 777 ${TMP}
  else
    TMP=$(mktemp -d /tmp/run_remote_tests.XXXX)
  fi
}

prepare_build_env() {
  info "Pilfering toolchain shell environment from Portage."
  local ebuild_dir="${TMP}/chromeos-base/autotest-build"
  mkdir -p "${ebuild_dir}"
  local E_only="autotest-build-9999.ebuild"
  cat > "${ebuild_dir}/${E_only}" <<EOF
inherit toolchain-funcs
SLOT="0"
EOF
  local E="chromeos-base/autotest-build/${E_only}"
  "ebuild-${FLAGS_board}" --skip-manifest "${ebuild_dir}/${E_only}" \
      clean unpack 2>&1 > /dev/null
  local P_tmp="/build/${FLAGS_board}/tmp/portage/"
  local E_dir="${E%%/*}/${E_only%.*}"
  export BUILD_ENV="${P_tmp}/${E_dir}/temp/environment"
}

autodetect_build() {
  if [ ${FLAGS_use_emerged} -eq ${FLAGS_TRUE} ]; then
    AUTOTEST_DIR="/build/${FLAGS_board}/usr/local/autotest"
    FLAGS_build=${FLAGS_FALSE}
    if [ ! -d "${AUTOTEST_DIR}" ]; then
      die \
"Could not find pre-installed autotest, you need to emerge-${FLAGS_board} \
autotest autotest-tests (or use --build)."
    fi
    info \
"As requested, using emerged autotests already installed at ${AUTOTEST_DIR}."
    return
  fi

  if [ ${FLAGS_build} -eq ${FLAGS_FALSE} ] &&
      cros_workon --board=${FLAGS_board} list |
      grep -q autotest; then
    AUTOTEST_DIR="${SRC_ROOT}/third_party/autotest/files"
    FLAGS_build=${FLAGS_TRUE}
    if [ ! -d "${AUTOTEST_DIR}" ]; then
      die \
"Detected cros_workon autotest but ${AUTOTEST_DIR} does not exist. Run \
repo sync autotest."
    fi
    info \
"Detected cros_workon autotests. Building and running your autotests from \
${AUTOTEST_DIR}. To use emerged autotest, pass --use_emerged."
    return
  fi

  # flag use_emerged should be false once the code reaches here.
  if [ ${FLAGS_build} -eq ${FLAGS_TRUE} ]; then
    AUTOTEST_DIR="${SRC_ROOT}/third_party/autotest/files"
    if [ ! -d "${AUTOTEST_DIR}" ]; then
      die \
"Build flag was turned on but ${AUTOTEST_DIR} is not found. Run cros_workon \
start autotest and repo sync to continue."
    fi
    info "Build and run autotests from ${AUTOTEST_DIR}."
  else
    AUTOTEST_DIR="/build/${FLAGS_board}/usr/local/autotest"
    if [ ! -d "${AUTOTEST_DIR}" ]; then
      die \
"Autotest was not emerged, ${AUTOTEST_DIR} does not exist. You should \
initilize it by either running 'build_packages' at least once, or running \
emerge-${FLAGS_board} autotest autotest-tests."
    fi
    info "Using emerged autotests already installed at ${AUTOTEST_DIR}."
  fi
}

# Convert potentially relative control file path to an absolute path.
normalize_control_path() {
    local control_file=$(remove_quotes "$1")
    if [[ ${control_file:0:1} == "/" ]]; then
      echo "${control_file}"
    else
      echo "${AUTOTEST_DIR}/${control_file}"
    fi
}

# Generate a control file which has a profiler enabled.
generate_profiled_control_file() {
  local control_file_path="$1"
  local results_dir="$2"

  mkdir -p "${results_dir}"
  local tmp="${results_dir}/$(basename "${control_file_path}").with_profiling"

  cat > "${tmp}" <<EOF
job.default_profile_only = True
job.profilers.add('${FLAGS_profiler}',
${FLAGS_profiler_args})
$(cat ${control_file_path})

job.profilers.delete('${FLAGS_profiler}')
EOF

  echo "${tmp}"
}

# Given a control_type (client or server) and a list of control files, assembles
# them all into a single control file. Useful for reducing repeated packaging
# between tests sharing the same resources.
generate_combined_control_file() {
  local control_type="$1"
  shift
  local control_files="$@"
  local control_file_count="$(echo ${control_files} | wc -w)"

  info "Combining the following tests in a single control file for efficiency:"

  local new_control_file="$(mktemp --tmpdir combined-control.XXXXX)"
  echo "TEST_TYPE=\"${control_type}\"" > ${new_control_file}
  echo "def step_init():" >> ${new_control_file}
  for i in $(seq 1 ${control_file_count}); do
    if [[ "${control_type}" == "client" ]]; then
      echo "    job.next_step('step${i}')" >> ${new_control_file}
    else
      echo "    step${i}()" >> ${new_control_file}
    fi
  done

  local index=1
  for control_file in ${control_files}; do
    control_file=$(remove_quotes "${control_file}")
    local control_file_path=$(normalize_control_path "${control_file}")
    info " * ${control_file}"

    echo "def step${index}():" >> ${new_control_file}
    cat ${control_file_path} | sed "s/^/    /" >> ${new_control_file}
    let index=index+1
  done
  if [[ "${control_type}" == "server" ]]; then
    echo "step_init()" >> ${new_control_file}
  fi
  echo "${new_control_file}"
}

# Given a list of control files, returns "client", "server", or "" respectively
# if there are only client, only server, or both types of control files.
check_control_file_types() {
  # Check to make sure only client or only server control files have been
  # requested, otherwise fall back to uncombined execution.
  local client_controls=${FLAGS_FALSE}
  local server_controls=${FLAGS_FALSE}

  for control_file in $*; do
    local control_file_path=$(normalize_control_path "${control_file}")
    local test_type=$(read_test_type "${control_file_path}")
    if [[ "${test_type}" == "client" ]]; then
      client_controls=${FLAGS_TRUE}
    else
      server_controls=${FLAGS_TRUE}
    fi
  done

  if [[ ${client_controls}^${server_controls} -eq ${FLAGS_FALSE} ]]; then
    if [[ ${client_controls} -eq ${FLAGS_TRUE} ]]; then
      echo "client"
    else
      echo "server"
    fi
  else
    echo ""
  fi
}


main() {
  cd "${SCRIPTS_DIR}"

  FLAGS "$@" || exit 1

  if [[ -z "${FLAGS_ARGV}" ]]; then
    echo ${FLAGS_HELP}
    exit 1
  fi

  # Check the validity of the user-specified result directory
  # It must be within the /tmp directory
  if [[ -n "${FLAGS_results_dir_root}" ]]; then
    SUBSTRING=${FLAGS_results_dir_root:0:5}
    if [[ ${SUBSTRING} != "/tmp/" ]]; then
      echo "User-specified result directory must be within the /tmp directory"
      echo "ex: --results_dir_root=/tmp/<result_directory>"
      exit 1
    fi
  fi

  set -e

  create_tmp

  trap cleanup EXIT

  remote_access_init
  # autotest requires that an ssh-agent already be running
  start_ssh_agent >/dev/null 2>&1

  learn_board
  if [[ -n "${FLAGS_autotest_dir}" ]]; then
    if [ ! -d "${FLAGS_autotest_dir}" ]; then
      die \
"Could not find the specified Autotest directory. Make sure the specified path \
exists inside the chroot. ${FLAGS_autotest_dir} $PWD"
    fi
    AUTOTEST_DIR=$(readlink -f "${FLAGS_autotest_dir}")
    FLAGS_build=${FLAGS_FALSE}
    info \
"As requested, using the specified Autotest directory at ${AUTOTEST_DIR}."
  else
    autodetect_build
  fi

  local control_files_to_run=""
  local chrome_autotests="${CHROME_ROOT}/src/chrome/test/chromeos/autotest/files"
  # Now search for tests which unambiguously include the given identifier
  local search_path=$(echo {client,server}/{tests,site_tests})
  # Include chrome autotest in the search path
  if [ -n "${CHROME_ROOT}" ]; then
    search_path="${search_path} ${chrome_autotests}/client/site_tests"
  fi

  is_suite() {
    expr match "${1}" "^${SUITES_PREFIX}" &> /dev/null
  }

  pushd ${AUTOTEST_DIR} > /dev/null
  for test_request in $FLAGS_ARGV; do
    test_request=$(remove_quotes "${test_request}")
    # Skip suites here.
    is_suite "${test_request}" && continue

    ! finds=$(find ${search_path} -maxdepth 2 -xtype f \( -name control.\* -or \
      -name control \) | egrep -v "~$" | egrep "${test_request}")
    if [[ -z "${finds}" ]]; then
      die "Cannot find match for \"${test_request}\""
    fi
    local matches=$(echo "${finds}" | wc -l)
    if [[ ${matches} -gt 1 ]]; then
      echo ">>> \"${test_request}\" is an ambiguous pattern.  Disambiguate by" \
           "passing one of these patterns instead:"
      for FIND in ${finds}; do
        echo "   ^${FIND}\$"
      done
      exit 1
    fi
    control_files_to_run="${control_files_to_run} '${finds}'"
  done

  # Do the suite enumeration upfront, rather than fail in the middle of the
  # process.
  ENUMERATOR_PATH="${AUTOTEST_DIR}/site_utils/"
  suite_list=()
  suite_map=()
  local control_type new_control_file
  for test_request in $FLAGS_ARGV; do
    test_request=$(remove_quotes "${test_request}")
    # Skip regular tests here.
    is_suite "${test_request}" || continue
    suite="${test_request/${SUITES_PREFIX}/}"

    info "Enumerating suite ${suite}"
    suite_list+=("${suite}")
    suite_map[${suite}]="$(${ENUMERATOR_PATH}/suite_enumerator.py \
                 --autotest_dir="${AUTOTEST_DIR}" ${suite})" ||
        die "Cannot enumerate ${suite}"
    # Combine into a single control file if possible.
    control_type="$(check_control_file_types ${suite_map[${suite}]})"
    info "Control type: ${control_type}"
    if [[ -n "${control_type}" ]]; then
      new_control_file="$(generate_combined_control_file ${control_type} \
                          ${suite_map[${suite}]})"
      suite_map[${suite}]="${new_control_file}"
    fi
  done

  echo ""

  if [[ -z "${control_files_to_run}" ]] && [[ -z "${suite_map[@]}" ]]; then
    die "Found no control files"
  fi

  [ ${FLAGS_build} -eq ${FLAGS_TRUE} ] && prepare_build_env

  # If profiling is disabled and we're running more than one test, attempt to
  # combine them for packaging efficiency.
  local new_control_file
  if [[ -z ${FLAGS_profiler} ]]; then
    if [[ "$(echo ${control_files_to_run} | wc -w)" -gt 1 ]]; then
      # Check to make sure only client or only server control files have been
      # requested, otherwise fall back to uncombined execution.
      local control_type=$(check_control_file_types ${control_files_to_run})
      if [[ -n ${control_type} ]]; then
        # Keep track of local control file for cleanup later.
        new_control_file="$(generate_combined_control_file ${control_type} \
            ${control_files_to_run})"
        control_files_to_run="${new_control_file}"
        echo ""
      fi
    fi
  fi

  info "Running the following control files ${FLAGS_iterations} times:"
  for control_file in ${control_files_to_run}; do
    info " * ${control_file}"
  done

  test_control_file() {
    control_file=$(remove_quotes "${control_file}")
    local control_file_path=$(normalize_control_path "${control_file}")
    local test_type=$(read_test_type "${control_file_path}")

    local option
    if [[ "${test_type}" == "client" ]]; then
      option="-c"
    else
      option="-s"
    fi
    echo ""
    info "Running ${test_type} test ${control_file}"
    local control_file_name=$(basename "${control_file}")
    local short_name=$(basename "$(dirname "${control_file}")")

    # testName/control --> testName
    # testName/control.bvt --> testName.bvt
    # testName/control.regression --> testName.regression
    # testName/some_control --> testName.some_control
    if [[ "${control_file_name}" != control ]]; then
      if [[ "${control_file_name}" == control.* ]]; then
        short_name=${short_name}.${control_file_name/control./}
      else
        short_name=${short_name}.${control_file_name}
      fi
    fi

    local results_dir_name="${short_name}"
    if [ "${FLAGS_iterations}" -ne 1 ]; then
      results_dir_name="${results_dir_name}.${i}"
    fi
    local results_dir="${TMP}/${results_dir_name}"
    rm -rf "${results_dir}"
    local verbose=""
    if [[ ${FLAGS_verbose} -eq 2 ]]; then
      verbose="--verbose"
    fi

    local image=""
    if [[ -n "${FLAGS_update_url}" ]]; then
      image="--image ${FLAGS_update_url}"
    fi

    RAN_ANY_TESTS=${FLAGS_TRUE}

    # Remove chrome autotest location prefix from control_file if needed
    if [[ ${control_file:0:${#chrome_autotests}} == \
          "${chrome_autotests}" ]]; then
      control_file="${control_file:${#chrome_autotests}+1}"
      info "Running chrome autotest ${control_file}"
    fi

    # If profiling is enabled, wrap up control file in profiling code.
    if [[ -n ${FLAGS_profiler} ]]; then
      if [[ "${test_type}" == "server" ]]; then
        die "Profiling enabled, but a server test was specified. \
Profiling only works with client tests."
      fi
      local profiled_control_file=$(generate_profiled_control_file \
          "${control_file_path}" "${results_dir}")
      info "Profiling enabled. Using generated control file at \
${profiled_control_file}."
      control_file="${profiled_control_file}"
    fi

    local autoserv_args="-m ${FLAGS_remote} --ssh-port ${FLAGS_ssh_port} \
        ${image} ${option} ${control_file} -r ${results_dir} ${verbose}"

    sudo chmod a+w ./server/{tests,site_tests}

    # --args must be specified as a separate parameter outside of the local
    # autoserv_args variable, otherwise ${FLAGS_args} values with embedded
    # spaces won't pass correctly to autoserv.
    echo ./server/autoserv ${autoserv_args} --args "${FLAGS_args}"

    local target="${TMP}/autoserv-log.txt"
    if [ ${FLAGS_verbose} -gt 0 ]; then
      target=1
    fi
    if [ ${FLAGS_build} -eq ${FLAGS_TRUE} ]; then
      # run autoserv in subshell
      # NOTE: We're being scrutinized by set -e. We must prevail. The whole
      # build depends on us. Failure is not an option.
      # The real failure is generated below by generate_test_report that
      # fails if complex conditions on test results are met, while printing
      # a summary at the same time.
      (. ${BUILD_ENV} && tc-export CC CXX PKG_CONFIG &&
       ./server/autoserv ${autoserv_args} --args "${FLAGS_args}") 2>&1 \
         >&${target} || true
    else
      ./server/autoserv ${autoserv_args} --args "${FLAGS_args}" 2>&1 \
         >&${target} || true
    fi
  }

  local control_file i suite
  # Number of global test iterations as defined with CLI.
  for i in $(seq 1 $FLAGS_iterations); do
    # Run regular tests.
    for control_file in ${control_files_to_run}; do
      test_control_file
    done
    # Run suites, pre-enumerated above.
    for suite in "${suite_list[@]}"; do
      info "Running suite ${suite}:"
      for control_file in ${suite_map[${suite}]}; do
        test_control_file
      done
    done
  done
  # Cleanup temporary combined control file.
  if [[ -n ${new_control_file} ]]; then
    rm ${new_control_file}
  fi
  popd > /dev/null

  echo ""
  info "Test results:"
  local report_args=("${TMP}" --strip="${TMP}/")
  if [[ ${FLAGS_whitelist_chrome_crashes} -eq ${FLAGS_TRUE} ]]; then
    report_args+=(--whitelist_chrome_crashes)
  fi
  generate_test_report "${report_args[@]}"

  print_time_elapsed
}

main "$@"
