# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

all: test_scripts

test_scripts:
	@echo "Preparing test scripts."

install:
	mkdir -p ${DESTDIR}/usr/bin
	mkdir -p ${DESTDIR}/usr/share/crostestutils
	install -m 0755 cros_run_unit_tests ${DESTDIR}/usr/bin
	install -m 0644 unit_test_black_list.txt ${DESTDIR}/usr/share/crostestutils

