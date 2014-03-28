#!/usr/bin/python
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

__author__ = 'deepakg@google.com'

"""
Remove the filtered lines in temp file from the whitelist files.
"""

import os
import sys
import tempfile


def main():
    """
    Remove lines from the whitelist.
    """
    if len(sys.argv)!=3:
        print ('InvalidArguments: We need 2 arguments. \n'
               'example: remove_from_whitelist.py gold_whitelist gold_temp.')
    else:
        whitelist_name = sys.argv[1]
        tempFile = sys.argv[2]
        if 'whitelist' in str(sys.argv[2]):
            tempFile = sys.argv[1]
            whitelist_name = sys.argv[2]
        whitelist = open(whitelist_name, 'r')
        remove = [x.strip() for x in open(tempFile, 'r').readlines()]
        output = tempfile.NamedTemporaryFile(dir=os.path.dirname(whitelist_name),
                                             delete=False)
        for line in whitelist:
            if line.startswith('#'):
                continue
            if line.strip() in remove:
                continue
            output.write(line)
        output.close()
        whitelist.close()
        os.rename(output.name, whitelist_name)
        print 'We have re-written the file ' + str(whitelist_name)


if __name__ == '__main__':
    main()
