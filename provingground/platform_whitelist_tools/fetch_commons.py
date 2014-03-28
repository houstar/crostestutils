#!/usr/bin/python
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file

__author__ = 'deepakg@google.com'

"""
Read *.debug files and create seperate files for each whitelist.
"""

import os
import re
import sys


class Read_File:
    """
    This class should read the debug files from the platform_ToolchainOptions
    tests and should list out all the whitelist files that are passing and not
    needed anymore and write them into a file.
    """

    def __init__(self):
        """
        Accept a file name that we should parse.
        """
        self.tests = [{'name':'gold', 'match':'Test gold',},
                      {'name':'now', 'match':'Test -Wl,-z,now',},
                      {'name':'relro', 'match':'Test -Wl,-z,relro',},
                      {'name':'pie', 'match':'Test -fPIE',},
                      {'name':'stack', 'match':'Test Executable Stack',}]


    def parse_file(self, current_file):
        """
        Read the contents and group them.

        current_file: name of the file to be parsed.
        """
        parse = False
        whitelist = None
        f = open(current_file)
        for line in f.readlines():
            if not parse:
                for item in self.tests:
                    if item['match'] in line:
                        whitelist = item

            if 'New passes' in line:
                parse = True
            elif parse:
                if re.match('\/', line):
                    pathname = line.strip()
                    whitelist.setdefault('files', {})
                    whitelist['files'].setdefault(pathname, 0)
                    whitelist['files'][pathname] += 1
                else:
                    parse = False


    def write_to_file(self, current_path, number_of_files):
        """
        Create a file for each whitelist and write the lines into it.

        current_path: Path to the directory containing the debug files.
        number_of_files: The number of DEBUG files in the directory.
        """
        for wl in self.tests:
            fpath = os.path.join(current_path, wl['name'])
            fopen = open(fpath, 'w+')
            for key, value in wl.items():
                if ((key != 'name' or key != 'match') and
                    value == number_of_files) :
                    fopen.write(key)
                    fopen.write('\n')
            print ('The whitelist files to be removed are written in ' + fpath)
            fopen.close()


def main():
    try:
        dir_path = sys.argv[1]
    except:
        dir_path = raw_input('Please enter the complete path to the directory '
                             'containing all the ToolchainOptions output - \n')
    dir_path = os.path.expanduser(dir_path)
    if not os.path.isdir(dir_path):
        raise RuntimeError('We need a directory with the ToolchainOptions '
                           'output files to continue.')
    fread = Read_File()
    file_count = 0
    for current_file in os.listdir(dir_path):
        file_path = os.path.join(dir_path, current_file)
        if file_path.endswith('.DEBUG'):
            fread.parse_file(file_path)
            file_count += 1
    fread.write_to_file(dir_path, file_count)


if __name__ == '__main__':
    main()
