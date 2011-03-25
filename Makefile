# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

all: test_scripts

test_scripts:
	@echo "Preparing test scripts."

install: test_scripts
	@echo "Test files installed."

