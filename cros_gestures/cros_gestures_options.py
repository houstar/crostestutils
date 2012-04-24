#!/usr/bin/python
# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Command line options to support cros_gestures.py.

This code assembles and parses options used by commands run
by cros_gestures.
"""

import getpass
import optparse
import os
import sys

import cros_gestures_commands
import cros_gestures_utils


color = cros_gestures_utils.Color()


# Find the hardware_Trackpad config file - we share it with the test.
base_dir = os.path.dirname(os.path.dirname(__file__))
trackpad_test_dir = os.path.join('/usr/local/autotest/tests/hardware_Trackpad')
if os.path.isdir(trackpad_test_dir):
  os.environ['TRACKPAD_TEST_DIR'] = trackpad_test_dir
else:
  trackpad_test_dir = os.environ.get('TRACKPAD_TEST_DIR')
  if not trackpad_test_dir or not os.path.isdir(trackpad_test_dir):
    cros_gestures_utils.OutputAndExit(
        'Unable to determine where the hardware_Trackpad test resides.'
        '\nPlease check the TRACKPAD_TEST_DIR environment variable.')

sys.path.insert(0, trackpad_test_dir)
from trackpad_util import read_trackpad_test_conf
from trackpad_util import trackpad_test_conf


def GetConfigOptions(current_dir):
  """Helper to retrieve config details like area and functionality."""
  found = False
  for path in [current_dir, os.environ.get('TRACKPAD_TEST_DIR')]:
    trackpad_test_conf_path = os.path.join(path, trackpad_test_conf)
    if os.path.isfile(trackpad_test_conf_path):
      found = True
      break
  if not found:
    msg = 'Unable to find config file: %s.' % trackpad_test_conf
    cros_gestures_utils.OutputAndExit(msg, red=True)

  # 'dir':['mix'] is a custom config entry for a handmade manifest file
  # with an area of 'mix' and a functionality of 'dir'.
  # examples: 'mix-dir.all-alex-mary_tut1-20111215_233052'
  #           'mix-dir.all-alex-user_tut1-20111215_233052'
  config_options = {'dir': ['mix']}
  for f in read_trackpad_test_conf('functionality_list', path):
    if f.name in config_options.iteritems():
      msg = ('Found a repeated functionality. Please check the conf file '
             'in %s' % path)
      cros_gestures_utils.OutputAndExit(msg, red=True)
    config_options[f.name] = f.area

  return config_options


def ParseArgs(usage, commands, admin=False):
  """Common processing of command line options."""
  base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

  parser = optparse.OptionParser(usage=usage)
  parser.add_option('-d', '--debug',
                    help='Show more output [default: %default]',
                    dest='debugout',
                    action='store_true',
                    default=False)
  parser.add_option('-D', '--detailed-debug',
                    help='Show even more output [default: %default]',
                    dest='detaileddebugout',
                    action='store_true',
                    default=False)
  parser.add_option('-m', '--model',
                    help='Gesture file model [default: %default]',
                    dest='model',
                    default=None)
  parser.add_option('-u', '--user',
                    help='Gesture file owner [default: %default]',
                    dest='userowner',
                    default=getpass.getuser())
  config_options = GetConfigOptions(base_dir)
  cros_gestures_commands.AddOptions(parser, config_options, admin=admin)
  options, args = parser.parse_args()
  options.config_options = config_options

  COMMANDS_STRING = ', '.join(sorted(commands.keys()))
  if len(args) < 1 or args[0].lower() not in commands:
    msg = 'Must supply 1 command from: %s.' % COMMANDS_STRING
    cros_gestures_utils.OutputAndExit(msg, red=True)
  command = args[0].lower()

  return options, args[1:], command
