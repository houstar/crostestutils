# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

all: test_scripts

test_scripts:
	@echo "Preparing test scripts."

install:
	mkdir -p "${DESTDIR}/usr/bin"
	mkdir -p "${DESTDIR}/usr/lib/crostestutils"
	mkdir -p "${DESTDIR}/usr/share/crostestutils"
	install -m 0644 lib/constants.py "${DESTDIR}/usr/lib/crostestutils"
	install -m 0755 cros_run_unit_tests "${DESTDIR}/usr/bin"
	install -m 0755 run_remote_tests.sh ${DESTDIR}/usr/bin
	install -m 0755 test_that ${DESTDIR}/usr/bin
	install -m 0755 bootperf-wrapper ${DESTDIR}/usr/bin/bootperf
	ln ${DESTDIR}/usr/bin/bootperf ${DESTDIR}/usr/bin/showbootdata
	install -m 0644 unit_test_black_list.txt \
		"${DESTDIR}/usr/share/crostestutils"
	install -m 0755 utils_py/generate_test_report.py \
		"${DESTDIR}/usr/lib/crostestutils"

	# Make symlinks for those python files in lib.
	ln -s "${DESTDIR}/usr/lib/crostestutils/generate_test_report.py" \
		"${DESTDIR}/usr/bin/generate_test_report"
