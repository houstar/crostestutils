#!/usr/bin/python
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Script to download ChromeOS images from google storage and output
# command to put said image on a USB stick or directly copy to a given stick.
# File needs to live in a place such that ./SRC_DIR reaches chromiumos/src
# Downloads image via gsutil to chromiumos/src/REL_DL_DIR.

"""Download and output or run image_to_usb command."""

import argparse
from multiprocessing import Manager
from multiprocessing import Process
import os
import shutil
import subprocess

# Relative path from this file to the chromiumos/src folder
SRC_DIR = '../../../'
# Path to default download directory relative to chromiumos/src folder,
# i.e. SRC_DIR+REL_DIR_DIR is a direct path from here to the directory
REL_DL_DIR = 'build/crosdl/'

# Conversions from common simplified/misspelled names of boards
PLATFORM_CONVERT = {'spring': 'daisy-spring', 'alex': 'x86-alex',
                    'alex-he': 'x86-alex-he', 'mario': 'x86-mario',
                    'zgb': 'x86-zgb', 'zgb-he': 'x86-zgb-he',
                    'pit': 'peach-pit', 'pheonix': 'phoenix'}


def _GstorageLinkGenerator(c, p, b):
  """Generate Google storage link given channel, platform, and build."""
  return 'gs://chromeos-releases/%s-channel/%s/%s/' % (c, p, b)


def _FolderNameGenerator(is_test, b, p, c, mp):
  """Generate a folder name unique to the downloaded build."""
  return '%s_%s_%s_%s%s' % ('Test' if is_test else 'Recovery', p, c, b, mp)


def main():
  """Download and output or run image_to_usb command."""
  parser = argparse.ArgumentParser(
      description=('Download a recovery or test image of ChromeOS.\n\n'
                   'e.g. ./crosdl.py -c dev -b 4996.0.0 -p '
                   'link daisy --tostick /dev/sdc /dev/sda.\n\nDefault '
                   'download location is src/%s.' % REL_DL_DIR),
      formatter_class=argparse.RawTextHelpFormatter)
  parser.add_argument('-r', '--recovery', dest='recovery',
                      action='store_true', help='Recovery image (default).')
  parser.add_argument('-t', '--test', dest='test', action='store_true',
                      help='Test image.')
  parser.add_argument('-c', '--channel', dest='channel', default='dev',
                      choices=['canary', 'dev', 'beta', 'stable'],
                      help='Channel (dev default).')
  parser.add_argument('-b', '--build', dest='build',
                      help='Build number, e.g. 4996.0.0.')
  parser.add_argument('-p', '--platform', dest='board', nargs='+',
                      help='Platform(s) to download, e.g. link daisy.')
  parser.add_argument('--premp', action='store_true',
                      help='PreMP image instead of MP.')
  parser.add_argument('--force', dest='force', action='store_true',
                      help=('Force new download of builds, even if files '
                            'already\nexist.'))
  parser.add_argument('--tostick', dest='to_stick', nargs='*',
                      help=('Copy to usb stick after download.  '
                            'Can either specify\ndrive(s) (e.g. /dev/sdc) '
                            'at which to install or leave\nblank for '
                            'interactive dialog later.  For multiple\n'
                            'boards, list out all drives (e.g. /dev/sdc '
                            '/dev/sda\n/dev/sdd).  Script will match this '
                            'list to the list of\ninput boards (in -p).'))
  parser.add_argument('--folder', dest='folder',
                      help=('Specify a new download folder (default is\nsrc/'
                            '%s).' % REL_DL_DIR))
  parser.add_argument('--deletefiles', dest='delete', action='store_true',
                      help=('Delete any files downloaded from this command'
                            'when\nfinished with copying to usb stick.  '
                            'Applicable only\nwhen using --tostick argument.'))
  parser.add_argument('--clearfolder', dest='clear', action='store_true',
                      help=('Delete all the sub-folders in the download '
                            'location\n(useful if you have filled up your '
                            'harddrive).'))
  arguments = parser.parse_args()

  # Set download folder as user defined or default.
  user_folder = arguments.folder
  if user_folder:
    download_folder = user_folder
  else:
    download_folder = os.path.join(SRC_DIR, REL_DL_DIR)

  # Delete download folder contents if clearfolder flag present.
  if arguments.clear:
    if os.path.exists(download_folder):
      print 'Deleting sub-folder contents of %s.' % download_folder
      for item in os.listdir(download_folder):
        item_path = os.path.join(download_folder, item)
        if os.path.isdir(item_path):
          shutil.rmtree(item_path)
    else:
      print 'Download folder %s did not exist.  Exiting.' % download_folder
    return

  # Require board and platform arguments if not clearing downloads.
  if not (arguments.board and arguments.build):
    print ('Must provide build number and platform(s).  See crosdl.py -h for '
           'usage description.')
    return

  # Require --deletefiles flag to be used only with --tostick flag.
  if arguments.delete and arguments.to_stick:
    print 'Will delete all newly downloaded files once finished.'
  elif arguments.delete:
    print ('This command will download and immediately delete all files.  '
           'You probably meant to use the --tostick flag as well.')
    return

  # Deal with board name(s).
  dupe_boards = []
  boards = arguments.board
  for i in xrange(len(boards)):
    boards[i] = boards[i].lower()
    if boards[i] in PLATFORM_CONVERT:
      boards[i] = PLATFORM_CONVERT[boards[i]]
    # Disallow duplicates.
    if boards[i] in dupe_boards:
      print '%s is listed twice in the boards list!' % boards[i]
      return 1
    dupe_boards.append(boards[i])

  # Set is_test based on input flags.
  is_test = arguments.test
  if is_test and arguments.recovery:
    print 'Please use only one of -r and -t.'
    return 1
  elif is_test:
    print 'Downloading test image(s).'
  else:
    print 'Downloading recovery image(s).'

  # String to identify premp/mp images.
  mp_str = '_premp' if arguments.premp else '_mp'

  # If installing multiple boards, must provide drive names.
  installing = type(arguments.to_stick) == list
  if len(boards) > 1 and installing:
    if not arguments.to_stick:
      print ('To install on multiple boards, please provide drive '
             'names (e.g. /dev/sdc /dev/sdd).  See -h for help.')
      return 1
    if len(arguments.to_stick) != len(boards):
      print ('Was given %d boards but %d usb drive locations.'
             % (len(boards), len(arguments.to_stick)))
      return 1
    for drive in arguments.to_stick:
      if not os.path.exists(drive):
        print '%s does not exist!' % drive

  # Subroutine to download an image for a single board.
  channel = arguments.channel
  build = arguments.build
  def _DownloadBoard(board, output_str, dl_error, dl_folder):
    """Download the file for a single board."""
    # Assume error happened unless changed below.
    dl_error[board] = True

    # See if file already exists locally.
    folder_name = _FolderNameGenerator(is_test=is_test, p=board, b=build,
                                       c=channel, mp=mp_str)
    folder_path = os.path.join(download_folder, folder_name)
    dl_folder[board] = folder_path
    if is_test:
      image_name = 'chromiumos_test_image.bin'
    else:
      image_name = 'recovery_image.bin'
    image_path = os.path.join(folder_path, image_name)

    # Skip for already present files, else download new file.
    if os.path.exists(image_path) and not arguments.force:
      print '%s: Found file locally.  Skipping download.' % board
    else:
      # Make folder if needed.
      if not os.path.exists(folder_path):
        subprocess.call(['mkdir', '-p', folder_path])

      # Generate search terms.
      folder = _GstorageLinkGenerator(c=channel, p=board, b=build)
      if is_test:
        file_search = '%s*test*.tar.xz' % folder
      else:
        file_search = '%s*recovery*%s*%s*.bin' % (folder, channel, mp_str)

      # Look for folder while file belongs.
      try:
        possible_files = subprocess.check_output(['gsutil', 'ls', folder])
      except subprocess.CalledProcessError:
        print ('%s: Could not find folder %s where this file is '
               'supposed to be.  Please check input values.' % (board, folder))
        output_str[board] = '%s: Could not find file.' % board
        return 1

      # Look for file in folder.
      try:
        possible_files = subprocess.check_output(['gsutil', 'ls', file_search])
      except subprocess.CalledProcessError:
        print ('%s: Could not find correct file (but found the '
               'correct folder).' % board)
        output_str[board] = '%s: Could not find file.' % board
        return 1

      # Locate exact filename.
      possible_files = possible_files.splitlines()
      if len(possible_files) != 1:
        print ('%s: Found %d possible files, not 1'
               % (board, len(possible_files)))
        output_str[board] = '%s: Could not find file.' % board
        return 1
      gsfile_path = possible_files[0]
      filename = os.path.basename(gsfile_path)

      # Download file to local machine.
      try:
        subprocess.call(['gsutil', 'cp', gsfile_path, folder_path])
      except subprocess.CalledProcessError:
        print ('gsutil error.  Try running this command outside of '
               'chroot?')
        output_str[board] = '%s: Could not run gsutil command.' % board
        return 1

      # Untar/rename files as needed.
      file_path = os.path.join(folder_path, filename)
      if is_test:
        subprocess.call(['tar', '-xf', file_path, '-C', folder_path])
        os.remove(file_path)
      else:
        os.rename(file_path, os.path.join(folder_path, image_name))

    # Return image_to_usb command and report successful download.
    path_to_script = os.path.join(SRC_DIR, 'scripts', 'image_to_usb.sh')
    output_str[board] = ('/usr/bin/sudo /bin/sh %s '
                         '--from=%s' % (path_to_script, image_path))
    dl_error[board] = False
    print '%s: DONE' % board

  # For each board, download file.
  manager = Manager()
  output_str = manager.dict()
  dl_error = manager.dict()
  dl_folder = manager.dict()
  jobs = []
  for board in boards:
    # Run download in separate process.
    proc = Process(target=_DownloadBoard, args=(board, output_str, dl_error,
                                                dl_folder,))
    jobs.append(proc)
    proc.start()

  # Wait for all downloads to finish.
  for job in jobs:
    job.join()

  # Print or run image_to_usb command.
  errors = ''
  if installing:
    jobs = []
    for i in xrange(len(boards)):
      board = boards[i]
      # If board downloaded without errors, install.  Else, skip.
      if not dl_error[board]:
        # If drive argument was provided, use it.  Else, leave it out.
        if arguments.to_stick:
          usb_drive = arguments.to_stick[i]
          cmd = '%s --to=%s -y' % (output_str[board], usb_drive)
          print 'Copying %s to %s.' % (board, usb_drive)
        else:
          cmd = output_str[board]
        proc = subprocess.Popen(cmd.split(' '))
        jobs.append(proc)
      else:
        errors += '%s\n' % output_str[board]
    # Wait for all copies to finish.
    for job in jobs:
      job.wait()
    if arguments.delete:
      print 'Deleting all files created for %s.' % board
      shutil.rmtree(dl_folder[board])
  else:
    for board in boards:
      if not dl_error[board]:
        print output_str[board]
      else:
        errors += '%s\n' % output_str[board]

  # Summarize errors, if any.
  print '\nScript complete.'
  print errors

if __name__ == '__main__':
  main()
