#!/usr/bin/python
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility functions for cros_gestures cli.

Utility functions shared by cros_gestures, cros_gestures_options and
cros_gestures_commands.
"""

import os
import re
import subprocess
import sys
import traceback

import cros_gestures_constants


FILE_PREFIX = 'file://'


#------------------------------------------------------------------------------
# Common utilities
#------------------------------------------------------------------------------
class Color(object):
  """Conditionally wraps text in ANSI color escape sequences."""
  BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)
  BOLD = -1
  COLOR_START = '\033[1;%dm'
  BOLD_START = '\033[1m'
  RESET = '\033[0m'

  def __init__(self, enabled=True):
    self._enabled = enabled

  def Color(self, color, text):
    """Returns text with conditionally added color escape sequences.

    Keyword arguments:
      color: Text color -- one of the color constants defined in this class.
      text: The text to color.

    Returns:
      If self._enabled is False, returns the original text. If it's True,
      returns text with color escape sequences based on the value of color.
    """
    if not self._enabled:
      return text
    if color == self.BOLD:
      start = self.BOLD_START
    else:
      start = self.COLOR_START % (color + 30)
    return start + text + self.RESET


color = Color()


def Output(message, red=False):
  """Common error printing - used for error importing required modules."""
  if red:
    message = color.Color(Color.RED, message)
  sys.stderr.write('%s\n' % message)


def OutputAndExit(message, red=False):
  """Common error printing - used for error importing required modules."""
  Output(message, red)
  sys.exit(1)


#------------------------------------------------------------------------------
# Very important but confusing import of boto library with proper .boto file
#------------------------------------------------------------------------------
def FindDependencies(boto_environ_var='BOTO_CONFIG'):
  """Find boto and gslib."""
  base_dir = os.path.dirname(__file__)
  gsutil_bin_dir = os.environ.get('GSUTIL_BIN_DIR', os.path.join(base_dir,
                                                                 'gsutil'))
  if gsutil_bin_dir and os.path.isdir(gsutil_bin_dir):
    os.environ['GSUTIL_BIN_DIR'] = os.path.realpath(gsutil_bin_dir)
  else:
    OutputAndExit('Unable to determine where gsutil is installed. '
                  'Please ensure the GSUTIL_BIN_DIR environment variable is '
                  'set to the gsutil directory.\nRetrieve gsutil from '
                  'http://commondatastorage.googleapis.com/pub/gsutil.tar.gz '
                  'if you do not have it.')
  found = False
  boto_list = (os.environ.get(boto_environ_var, None),
               os.path.join(base_dir, '.boto'),
               os.path.join(base_dir, 'untrusted',
                            'chromeos.gestures.untrusted.write.boto'))
  for boto_config in boto_list:
    if boto_config and os.path.isfile(boto_config):
      os.environ['BOTO_CONFIG'] = os.path.realpath(boto_config)
      found = True
      break
  if not found:
    OutputAndExit('Unable to determine where .boto is installed. Please ensure '
                  'the %s environment variable is set to the '
                  'full path of the .boto file.\n' % boto_environ_var)

  # .boto enforces the trustworthiness - this is just a hint.
  if boto_config.find('untrusted') > -1:
    cros_gestures_constants.trusted = False

  # Before importing boto, find where gsutil is installed and include its
  # boto sub-directory at the start of the PYTHONPATH, to ensure the versions of
  # gsutil and boto stay in sync after software updates. This also allows gsutil
  # to be used without explicitly adding it to the PYTHONPATH.
  boto_lib_dir = os.path.join(gsutil_bin_dir, 'boto')
  if not os.path.isdir(boto_lib_dir):
    OutputAndExit('There is no boto library under the gsutil install directory '
                  '(%s).\nThe gsutil command cannot work properly when '
                  'installed this way.\nPlease re-install gsutil per the '
                  'installation instructions.' % gsutil_bin_dir)
  sys.path.insert(0, os.path.realpath(boto_lib_dir))

  # Needed so that cros_gestures_commands can import from gslib/commands and for
  # oauth2 import.
  sys.path.insert(0, os.path.realpath(gsutil_bin_dir))

  return gsutil_bin_dir, boto_config


#------------------------------------------------------------------------------
# Exception handlers
#------------------------------------------------------------------------------
def HandleUnknownFailure(e):
  """Called if we fall through all known/handled exceptions.
  Allows us to # print a stacktrace if -D option used.
  """
  if cros_gestures_constants.debug > 2:
    stack_trace = traceback.format_exc()
    prefix = color.Color(Color.RED, 'DEBUG: Exception stack trace:')
    OutputAndExit('%s\n    %s\n' % (prefix, re.sub('\\n', '\n    ',
                                    stack_trace)))
  else:
    OutputAndExit('Failure: %s.' % e)


def HandleCrosGesturesException(e):
  """Commonly raised exception in command line processing."""
  if e.informational:
    Output(e.reason)
  else:
    prefix = color.Color(Color.RED, 'CrosGesturesException:')
    OutputAndExit('%s %s' % (prefix, e.reason))


def HandleControlC(signal_num, cur_stack_frame):
  """Called when user hits ^C so we can print a brief message.
  This is instead of the normal Python stack trace (unless -D option is used).
  """
  if cros_gestures_constants.debug > 2:
    stack_trace = ''.join(traceback.format_list(traceback.extract_stack()))
    prefix = color.Color(Color.RED, 'DEBUG: Caught signal %d - '
                                    'Exception stack trace:' % signal_num)
    OutputAndExit('%s\n    %s' % (prefix, re.sub('\\n', '\n    ', stack_trace)))
  else:
    OutputAndExit('Caught signal %d - exiting' % signal_num, red=True)


#------------------------------------------------------------------------------
# Command validation utility functions.
#------------------------------------------------------------------------------
def HaveFileUris(args):
  """Checks whether args contains any file URIs."""
  for uri_str in args:
    if uri_str.lower().startswith(FILE_PREFIX) or uri_str.find(':') == -1:
      return True
  return False


def StripFileUris(args):
  """Removes file:// from any file URIs since we prefix our file URIs."""
  new_args = []
  file_prefix_len = len(FILE_PREFIX)
  for uri_str in args:
    if uri_str.lower().startswith(FILE_PREFIX):
      new_args.append(uri_str[file_prefix_len:])
    else:
      new_args.append(uri_str)
  return new_args


#------------------------------------------------------------------------------
# Wrap command-line gsutil.
#------------------------------------------------------------------------------
def RunGSUtil(bin_dir, logger, cmd, headers=None, sub_opts=None, args=None,
              show_output=True):
  """Executes gsutil with the provided command.

  Args:
    bin_dir: Location of gsutil
    logger: active logger
    cmd: Command to execute: ls, cat, rm, cp, setacl, getacl, ver
    headers: send optional headers with the command
    sub_options: optional command-specific flags
    args: cmd specific args (e.g. filenames)

  Returns:
    Returns the returncode (0=success, nonzero=failed)
  """
  debug_options = ('', '', '-d', '-D', '-DD')
  if not headers:
    headers = ''
  else:
    headers = ' -h ' + ' -h '.join(headers)
  if not sub_opts:
    sub_opts = ''
  else:
    sub_opts = ' '.join(sub_opts)
  if args:
    args = '"' + '" "'.join(args) + '"'
  else:
    args = ''
  cmd = ('%s %s %s %s %s %s' % (os.path.join(bin_dir, 'gsutil'),
                                debug_options[cros_gestures_constants.debug],
                                headers, cmd, sub_opts, args)).strip()
  logger.debug('Running command "%s"', cmd)
  try:
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    stdout, _ = p.communicate()
    if show_output:
      print stdout.strip()
    return p.returncode
  except OSError, e:
    if not show_output:
      return e.errno
    if e.errno == 2:
      OutputAndExit('File not found: %s' % args)
    OutputAndExit('OSError: (%s) %s.' % (e.errno, e.strerror))
  except Exception, e:
    HandleUnknownFailure(e)
  return 1
