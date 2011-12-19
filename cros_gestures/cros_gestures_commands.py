#!/usr/bin/python
# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Commands to support cros_gestures

This code is modeled after and derived from the Command class in
gsutil/gslib/command.py for maximum re-use.
"""

__version__ = '0.9.1'

import datetime
import hashlib
import logging
import optparse
import os
import re
import sys

import constants
import cros_gestures_utils
from exception import CrosGesturesException


color = cros_gestures_utils.Color()

LOG = logging.getLogger('cros_gestures_commands')
# Mon, 25 Jul 2011 08:20:08
DISPLAY_TIME_FORMAT = '%a, %d %b %Y %H:%M:%S'
# 20110725_082008
FILE_TIME_FORMAT = '%Y%m%d_%H%M%S'


def AddOptions(parser, config_options, admin=False):
  """Add command line option group for cros_gestures_commands.

  Add helpful command line options related to commands defined
  in this file.

  -F, --force-rm: [invalidate/rm] confirmation of irreversible file removal.
  -L, --list-metadata: [ls] most verbose ls command.
  -U, --user-override: [all] substitute an alternate user tag in file namespace.
  --print-filenames: [cat] include filename (helps cat of multiple cat files).
  --download-dir: [download] place downloaded files out of current dir.
  --upload-functionality: [upload]: override filename functionality.
  --upload-fwversion: [upload]: override filename fwversion.
  --upload-tag: [upload] set a tag (to arbitrarily group files).
  """
  group = optparse.OptionGroup(parser, 'Command Options')
  group.add_option('-F', '--force-rm',
                    help='Force %s of file [default: %s]' % (
                        color.Color(cros_gestures_utils.Color.BOLD, 'rm'),
                        '%default'),
                    dest='forcerm',
                    action='store_true',
                    default=False)
  group.add_option('-L', '--list-metadata',
                    help='Show file metadata with %s [default: %s]' % (
                        color.Color(cros_gestures_utils.Color.BOLD, 'list'),
                        '%default'),
                    dest='listmetadata',
                    action='store_true',
                    default=False)
  group.add_option('-U', '--user-override',
                    help='Override filename user of file [default: %s]' %
                        '%default',
                    dest='useroverride',
                    action='store_true',
                    default=False)
  group.add_option('', '--print-filenames',
                    help='Show file names with %s output [default: %s]' % (
                        color.Color(cros_gestures_utils.Color.BOLD, 'cat'),
                        '%default'),
                    dest='catfilenames',
                    action='store_true',
                    default=False)
  # Admin commands use different options.
  if not admin:
    group.add_option('', '--download-dir',
                      help='Set %s directory [default: %s]' % (
                          color.Color(cros_gestures_utils.Color.BOLD,
                                      'download'),
                          '%default'),
                      dest='downloaddir',
                      default=None)
    group.add_option('', '--upload-functionality',
                      help='Set functionality during %s: %s [default: %s]' % (
                          color.Color(cros_gestures_utils.Color.BOLD, 'upload'),
                          ', '.join(sorted(config_options.keys())),
                          '<from filename>'),
                      dest='uploadfunctionality',
                      default=None)
    group.add_option('', '--upload-fwversion',
                      help='Set fwversion during %s [default: %s]' % (
                          color.Color(cros_gestures_utils.Color.BOLD, 'upload'),
                          '%default'),
                      dest='uploadfwversion',
                      default=None)
    group.add_option('', '--upload-tag',
                      help='Supply %s tag for custom grouping [default: %s]' % (
                          color.Color(cros_gestures_utils.Color.BOLD, 'upload'),
                          '%default'),
                      dest='uploadtag',
                      default=None)
  parser.add_option_group(group)


def FixupOptionsFromFilename(source_file, options):
  """Setup default options (metadata) from filename if possible.

  template filename:
   area-functionalitynamewithunderscores.subname-model-tester-timestamp.dat
   0: area
   1: functionality [optional subname(s) separated by period]
   2: model
   3: [fw version]
   4: [optional attributes - each separated by hyphen]
   5: tester
   6: timestamp
  """
  options.uploadarea = None  # Create nonexistent attributes
  options.uploadcreated = None
  # TODO(Truty): handle firmware version in the filename.
  #              also, possible for no sub-name
  filename_parse = re.compile(
      '([\w]+)-([\w]+)\.[\w.]+-([\w]+)-([\w]+)-([\w]+)')
  m = re.match(filename_parse, source_file)
  if not m or m.lastindex < 5:
    raise CrosGesturesException(
        'This filename is not formatted properly. Expecting: '
        'area-functionality.subname-model-tester-timestamp.dat. '
        'Skipping %s.' % source_file)
  gs_area, gs_functionality, gs_model, gs_tester, gs_time = m.groups()
  if gs_area:
    options.uploadarea = gs_area
  if gs_functionality:
    options.uploadfunctionality = gs_functionality
  if gs_model:
    if not options.model:
      options.model = gs_model
    if gs_model != options.model:
      raise CrosGesturesException(
          '--model (%s) is different than file name model (%s).' %
          (options.model, gs_model))
  if gs_tester and gs_tester != options.userowner:
    LOG.warning(
        '--user (%s) is different than file name tester (%s).',
        options.userowner, gs_tester)
    if not options.useroverride:
      options.userowner = gs_tester
  if gs_time:
    options.uploadcreated = datetime.datetime.strptime(
        gs_time, FILE_TIME_FORMAT).strftime(DISPLAY_TIME_FORMAT)
  # Extra validations
  if options.uploadfunctionality not in options.config_options:
      raise CrosGesturesException('The config file does not expect this '
                                  'functionality: %s' %
                                  options.uploadfunctionality)
  if (options.uploadarea not in
      options.config_options[options.uploadfunctionality]):
      raise CrosGesturesException('The area %s is not expected with %s.' %
                                  (options.uploadarea,
                                   options.uploadfunctionality))


class GestureUri(object):
  """Very thin wrapper around our gesture uri's."""
  def __init__(self, options):
    self.options = options

  @staticmethod
  def HasGSUri(uri_str):
    """Check one uri for our provider."""
    return uri_str.lower().startswith('gs://')

  @staticmethod
  def HasGSUris(args):
    """Checks whether args contains any provider URIs (like 'gs://').

    Args:
      args: command-line arguments

    Returns:
      True if args contains any provider URIs.
    """
    for uri_str in args:
      if GestureUri.HasGSUri(uri_str):
        return True
    return False

  def MakeGestureUri(self, uri_str=None):
    """Gesture files are prefaced by their ownername."""
    assert uri_str
    if uri_str == '*' and not self.options.model:
      self.options.model = '*'
    if not self.options.model:
      raise CrosGesturesException('Please supply a model to MakeGestureUri.')
    if not self.options.userowner:
      raise CrosGesturesException('Please supply a user to MakeGestureUri.')
    if not uri_str:
      raise CrosGesturesException('Unexpected empty uri.')
    if constants.trusted:
      user_type = 'trusted-dev'
    else:
      user_type = 'untrusted-dev'
    return 'gs://chromeos-gestures-%s/%s/%s/%s' % (user_type,
                                                   self.options.model,
                                                   self.options.userowner,
                                                   uri_str)

  @staticmethod
  def MakeValidUri(uri_str):
    """Gesture files headed to the valid bucket."""
    if not GestureUri.HasGSUri(uri_str):
      raise CrosGesturesException('Validate requires a gs:// uri.')
    return re.sub('gs://chromeos-gestures.*trusted-dev/',
                  'gs://chromeos-gestures-valid/', uri_str)

  def MakeGestureUris(self, args):
    """Fixup args to be valid gs uri's if needed."""
    new_args = []
    for uri_str in args:
      if GestureUri.HasGSUri(uri_str):
        new_arg = uri_str
      else:
        uri_str = os.path.basename(uri_str)
        FixupOptionsFromFilename(uri_str, self.options)
        new_arg = self.MakeGestureUri(uri_str)
      new_args.append(new_arg)
    return new_args


class GestureCommand(object):
  """Class that contains all our Gesture command code."""

  def __init__(self, gsutil_bin_dir):
    """Instantiates GestureCommand class. Modeled after gslib/command/Command.

    Args:
      gsutil_bin_dir: bin dir from which gsutil is running.
    """
    self.gsutil_bin_dir = gsutil_bin_dir

  def _FileExists(self, file_name):
    """Helper to see if a fully path-included remote file exits."""
    return 0 == cros_gestures_utils.RunGSUtil(self.gsutil_bin_dir, LOG, 'ls',
                                              args=[file_name],
                                              show_output=False)

  def RunGSUtil(self, cmd, headers=None, sub_opts=None, args=None,
                  show_output=True):
    """Executes common gsutil run command utility."""
    return cros_gestures_utils.RunGSUtil(self.gsutil_bin_dir, LOG, cmd,
                                         headers, sub_opts, args, show_output)

  def CatGestureCommand(self, args, options):
    """Cat a single gesture file from Google Storage."""
    guri = GestureUri(options)
    args = guri.MakeGestureUris(args)

    if options.catfilenames:
      sub_opts = ['-h']
    else:
      sub_opts = None
    return self.RunGSUtil(cmd='cat', sub_opts=sub_opts, args=args)

  def DownloadGestureCommand(self, args, options):
    """Download a single gesture file from Google Storage."""
    # TODO(Truty): add md5/md5 header and verify.
    local_files = args[:]
    guri = GestureUri(options)
    args = guri.MakeGestureUris(args)
    rc = 0
    for i in xrange(len(args)):
      remote_file = args[i]
      if not self._FileExists(remote_file):
        LOG.warning(color.Color(
            cros_gestures_utils.Color.RED, 'File %s not found.' % remote_file))
        continue
      local_file = local_files[i]
      if options.downloaddir:
        if not os.path.exists(options.downloaddir):
          os.makedirs(options.downloaddir)
        local_file = os.path.join(options.downloaddir, local_file)
      if os.path.isfile(local_file):
        raise CrosGesturesException('Local file %s already exists.' %
                                    local_file)
      rc += self.RunGSUtil(cmd='cp', args=[remote_file, local_file])
    return rc

  def InvalidateGestureCommand(self, args, options):
    """Allows a gesture file to be blocked to tests.

    See ValidateGestureCommand() for more detail.
    """
    if not options.forcerm:
      raise CrosGesturesException(
          'invalidate requires -F to force file removal.')
    guri = GestureUri(options)
    source_file = guri.MakeGestureUris(args)[0]
    target_file = GestureUri.MakeValidUri(source_file)
    if not self._FileExists(target_file):
      raise CrosGesturesException('Validated file %s cannot be found.'
                                  % target_file)
    return self.RunGSUtil(cmd='rm', args=[target_file])

  def ListGesturesCommand(self, args, options):
    """List gestures (and metadata) in Google Storage."""
    guri = GestureUri(options)
    if not args:
      args = [guri.MakeGestureUri('*')]
    else:
      args = guri.MakeGestureUris(args)

    if options.listmetadata:
      sub_opts = ['-L']
      LOG.info('This can take a little longer to retrieve metadata.')
    else:
      sub_opts = None
    return self.RunGSUtil(cmd='ls', sub_opts=sub_opts, args=args)

  def RemoveGesturesCommand(self, args, options):
    """Remove gestures in Google Storage."""
    guri = GestureUri(options)
    args = guri.MakeGestureUris(args)
    if not options.forcerm:
      raise CrosGesturesException('rm requires -F to force file removal.')
    return self.RunGSUtil(cmd='rm', args=args)

  def UploadGestureCommand(self, args, options):
    """Upload a single gesture file to Google Storage."""
    local_file = args[0]
    guri = GestureUri(options)
    remote_file = guri.MakeGestureUris(args)[0]
    if self._FileExists(remote_file):
      raise CrosGesturesException('File %s already exists.' % remote_file,
                                  informational=True)
    if not os.path.isfile(local_file):
      raise CrosGesturesException('Cannot find source file: %s.' % local_file)
    if not options.uploadfunctionality:
      raise CrosGesturesException('upload requires '
                                  '--upload-functionality=functionality. '
                                  '\n\t\tfunctionality is one of:\n\t\t\t%s' %
                                  ('\n\t\t\t'.join(options.config_options)))
    if not options.uploadarea:
      raise CrosGesturesException('upload requires an upload area.')
    if not options.model:
      raise CrosGesturesException('upload requires --model=model#.')
    # uploadfwversion is NOT required.

    # If this is not project-private, then only the owner can mark the
    # file object public-read (we call that 'validation').
    sub_opts = ['-a', 'project-private']
    hprefix = 'x-goog-meta'

    f = open(local_file, 'r')
    file_contents = f.read()
    f.close()
    headers = ["'Content-MD5':%s" % hashlib.md5(file_contents).hexdigest(),
               '"%s-area:%s"' % (hprefix, options.uploadarea),
               '"%s-function:%s"' % (hprefix, options.uploadfunctionality),
               '"%s-fw_version:%s"' % (hprefix, options.uploadfwversion),
               '"%s-model:%s"' % (hprefix, options.model),
               '"%s-created:%s"' % (hprefix, options.uploadcreated)]
    if options.uploadtag:
      headers.append('"%s-tag:%s"' % (hprefix, options.uploadtag))
    return self.RunGSUtil(cmd='cp', headers=headers, sub_opts=sub_opts,
                            args=[local_file, remote_file])

  def ValidateGestureCommand(self, args, options):
    """Allows a gesture file to be consumed by tests.

    Validate makes files available for unauthenticated access.  Note that
    in copying the file to the valid bucket, the object's metadata is lost.
    It's metadata remains in the source folder, though, for filtering use.
    1. 'Invalid' files are not accessible by unauthenticated-public.
    2. It is desirable to know the date of the validation.  The logic of
       interpreting 'date-validated is:
         If the file is 'valid', then 'Last mod' is the 'date-validated'.
    Public access of 'validated' files is through:
      http://chromeos-gestures-valid.commondatastorage.googleapis.com/
    """
    guri = GestureUri(options)
    source_file = guri.MakeGestureUris(args)[0]
    target_file = GestureUri.MakeValidUri(source_file)
    if not self._FileExists(source_file):
      raise CrosGesturesException('File %s cannot be found.' % source_file)
    if self._FileExists(target_file):
      raise CrosGesturesException('Validated file %s already exists.'
                                  % target_file)
    rc = self.RunGSUtil(cmd='cp', args=[source_file, target_file])
    if not rc:
      rc = self.RunGSUtil(cmd='setacl', args=['public-read', target_file])
    return rc

  def VersionCommand(self, args, options):
    """Print version information for gsutil."""
    msg = color.Color(cros_gestures_utils.Color.BOLD,
                      'cros_gestures version %s\n' % __version__)
    sys.stderr.write(msg)
    return self.RunGSUtil(cmd='ver')
