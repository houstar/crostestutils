#!/usr/bin/python
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Script to download ChromeOS images or test folders from google storage and
# output download location or directly copy (image) to a usb stick.
# In order to make usb sticks, file needs to be run from a place such that
# ./REL_SRC_DIR reaches chromiumos/src, or the src_dir input must be
# specified.
# Downloads image via gsutil to chromiumos/src/REL_DL_DIR.

"""Download and output or run cros flash command to copy image to usb."""

import argparse
from multiprocessing import Manager
from multiprocessing import Process
import os
import shutil
import subprocess

# Relative path from this file to the chromiumos/src folder
REL_SRC_DIR = '../../../'
# Path to default download directory relative to chromiumos/src folder,
# i.e. REL_SRC_DIR+REL_DIR_DIR is a direct path from here to the directory
REL_DL_DIR = 'build/crosdl/'

# Conversions from common simplified/misspelled names of boards
PLATFORM_CONVERT = {'spring': 'daisy-spring', 'alex': 'x86-alex',
                    'alex-he': 'x86-alex-he', 'mario': 'x86-mario',
                    'zgb': 'x86-zgb', 'zgb-he': 'x86-zgb-he',
                    'pit': 'peach-pit', 'pi': 'peach-pi',
                    'snow': 'daisy', 'lucas': 'daisy', 'big': 'nyan-big'}

# Download types
RECOVERY = 0
TEST = 1
AUTOTEST = 2
FACTORY = 3


def _GenerateGstorageLink(c, p, b):
  """Generate Google storage link given channel, platform, and build."""
  return 'gs://chromeos-releases/%s-channel/%s/%s/' % (c, p, b)


def _GenerateFolderName(download_type, b, p, c, mp):
  """Generate a folder name unique to the download."""
  if download_type == TEST:
    type_string = 'Test'
  elif download_type == AUTOTEST:
    type_string = 'Autotest'
  elif download_type == FACTORY:
    type_string = 'Factory'
  else:
    type_string = 'Recovery'
  return '%s_%s_%s_%s%s' % (p, b, c, type_string, mp)


def main():
  """Download and output or run cros flash command."""
  parser = argparse.ArgumentParser(
      description=('Download a testing resource: recovery image, test image, '
                   'autotest folder, or factory\nbundle.  Optionally make usb '
                   'sticks from these downloaded images.\n\n'
                   'e.g. ./crosdl.py -c dev -b 4996.0.0 -p '
                   'link daisy --tostick /dev/sdc /dev/sda.\n\nDefault '
                   'download location is src/%s.' % REL_DL_DIR),
      formatter_class=argparse.RawDescriptionHelpFormatter)
  group_type = parser.add_mutually_exclusive_group()
  group_type.add_argument('-r', '--recovery', dest='recovery',
                          action='store_true', help='Recovery image (default).')
  group_type.add_argument('-t', '--test', dest='test', action='store_true',
                          help='Test image.')
  group_type.add_argument('-a', '--autotest', dest='autotest',
                          action='store_true', help='Autotest folder.')
  group_type.add_argument('-f', '--factory', dest='factory',
                          action='store_true', help='Factory bundle.')
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
                            'already exist.'))
  group_usb = parser.add_mutually_exclusive_group()
  group_usb.add_argument('--to_stick', dest='to_stick', nargs='*',
                         help=('Copy to usb stick after download in a one-'
                               'to-one way.  Can either specify drive(s) '
                               '(e.g. /dev/sdc) at which to install or leave '
                               'blank for interactive dialog later.  For '
                               'multiple boards, list out all drives (e.g. '
                               '/dev/sdc /dev/sda /dev/sdd).  Script will '
                               'match this list directly to the list of input '
                               'boards (in -p).'))
  group_usb.add_argument('--one_to_multiple_sticks', dest='to_many', nargs='+',
                         help=('Copy one image to the listed multiple usb '
                               'sticks after download (e.g. /dev/sdc /dev/sdd)'
                               '.  Must specify only one board at a time.'))
  parser.add_argument('--folder', dest='folder',
                      help=('Specify a new download folder (default is src/'
                            '%s).' % REL_DL_DIR))
  parser.add_argument('--delete_files', dest='delete', action='store_true',
                      help=('Delete any files downloaded from this command'
                            'when finished with copying to usb stick.  '
                            'Applicable only when using --to_stick or '
                            '--one_to_multiple_sticks arguments.'))
  parser.add_argument('--clear_folder', dest='clear', action='store_true',
                      help=('Delete all the sub-folders in the download '
                            'location (useful if you have filled up your '
                            'harddrive).'))
  arguments = parser.parse_args()

  # Find src/ dir.
  script_file_dir = os.path.dirname(os.path.realpath(__file__))
  src_dir = os.path.join(script_file_dir, REL_SRC_DIR)
  src_dir = os.path.abspath(src_dir)
  if os.path.basename(src_dir) != 'src':
    print 'Could not find src/ directory!  Has this script been moved?'
    return

  # Set download folder as user defined or default.
  user_folder = arguments.folder
  if user_folder:
    download_folder = user_folder
  else:
    download_folder = os.path.join(src_dir, REL_DL_DIR)

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
  if arguments.delete and (arguments.to_stick or arguments.to_many):
    print 'Will delete all newly downloaded files once finished.'
  elif arguments.delete:
    print ('This command will download and immediately delete all files.  '
           'You probably meant to use the --tostick flag as well.')
    return

  # Deal with board name(s).
  dupe_boards = []
  boards = arguments.board
  for i in xrange(len(boards)):
    boards[i] = boards[i].lower().replace('_', '-')
    if boards[i] in PLATFORM_CONVERT:
      boards[i] = PLATFORM_CONVERT[boards[i]]
    # Disallow duplicates.
    if boards[i] in dupe_boards:
      print '%s is listed twice in the boards list!' % boards[i]
      return 1
    dupe_boards.append(boards[i])

  # Set is_test based on input flags.
  if arguments.test:
    print 'Downloading test image(s).'
    download_type = TEST
    is_image = True
  elif arguments.autotest:
    print 'Downloading autotest folder(s).'
    download_type = AUTOTEST
    is_image = False
  elif arguments.factory:
    print 'Downloading factory folder(s).'
    download_type = FACTORY
    is_image = False
  else: # RECOVERY
    print 'Downloading recovery image(s).'
    download_type = RECOVERY
    is_image = True

  # String to identify premp/mp images.
  mp_str = ''
  if download_type == RECOVERY:
    mp_str = '_premp' if arguments.premp else '_mp'

  # Disallow 'to many' option for more than one board
  installing_many = arguments.to_many
  if len(boards) > 1 and installing_many:
    print ('Please only specify one board if using --one_to_multiple_'
           'sticks option.  See help menu.')
    return 1

  # If installing multiple images, must provide drive names.
  installing_one = type(arguments.to_stick) == list
  if installing_one and (len(boards) > 1 or len(arguments.to_stick) > 1):
    if not arguments.to_stick:
      print ('Error: To make sticks for multiple boards, please provide drive '
             'names (e.g. /dev/sdc /dev/sdd).  See -h for help.')
      return 1
    if len(arguments.to_stick) != len(boards):
      print ('Error: Was given %d boards but %d usb drive locations.'
             % (len(boards), len(arguments.to_stick)))
      return 1
    for drive in arguments.to_stick:
      if not os.path.exists(drive):
        print '%s does not exist!' % drive

  # Disallow 'to usb' options if not an image
  if not is_image and (installing_one or installing_many):
    print ('Can only copy to usb if downloading an image.  See help menu.')
    return 1

  # Request sudo permissions if installing later.
  if installing_one or installing_many:
    subprocess.call(['sudo', '-v'])

  # Subroutine to download a file for a single board.
  channel = arguments.channel
  build = arguments.build
  def _DownloadBoard(board, output_str, dl_error, dl_folder):
    """Download the file for a single board."""
    # Assume error happened unless changed below.
    dl_error[board] = True

    # See if file already exists locally.
    folder_name = _GenerateFolderName(download_type=download_type, p=board,
                                      b=build, c=channel, mp=mp_str)
    folder_path = os.path.join(download_folder, folder_name)
    dl_folder[board] = folder_path
    if download_type == TEST:
      target_name = 'chromiumos_test_image.bin'
    elif download_type == AUTOTEST:
      target_name = ''
    elif download_type == FACTORY:
      target_name = ''
    else: # RECOVERY
      target_name = 'recovery_image.bin'
    target_path = os.path.join(folder_path, target_name)

    # Skip for already present files, else download new file.
    if os.path.exists(target_path) and not arguments.force:
      print '%s: Found file locally.  Skipping download.' % board
    else:
      # Make folder if needed.
      if not os.path.exists(folder_path):
        subprocess.call(['mkdir', '-p', folder_path])

      # Generate search terms.
      folder = _GenerateGstorageLink(c=channel, p=board, b=build)
      if download_type == TEST:
        file_search = '%s*test*.tar.xz' % folder
      elif download_type == AUTOTEST:
        file_search = '%s*hwqual*.tar.bz2' % folder
      elif download_type == FACTORY:
        file_search = '%s*factory*.zip' % folder
      else: # RECOVERY
        file_search = '%s*recovery*%s*%s*.bin' % (folder, channel, mp_str)
        file_search_2 = ('%schromeos-signing*/*recovery*%s*%s*.bin'
                         % (folder, channel, mp_str))

      # Output error if no files found
      def _no_file_error(message):
        """Actions to take if file is not found."""
        print '%s: %s' % (board, message)
        output_str[board] = '%s: Could not find file.' % board

      # Look for folder while file belongs.
      try:
        possible_files = subprocess.check_output(['gsutil', 'ls', folder])
      except subprocess.CalledProcessError:
        _no_file_error('Could not find folder %s where this file is supposed '
                       'to be.  Please check input values.' % folder)
        return 1

      # Look for file in folder.
      try:
        possible_files = subprocess.check_output(['gsutil', 'ls', file_search])
      except subprocess.CalledProcessError:
        if download_type == RECOVERY:
          try:
            possible_files = subprocess.check_output(['gsutil', 'ls',
                                                      file_search_2])
          except subprocess.CalledProcessError:
            _no_file_error('Could not find file but found folder.')
            return 1
        else:
          _no_file_error('Could not find file but found folder.')
          return 1

      # Locate exact file_name.
      possible_files = possible_files.splitlines()
      if len(possible_files) != 1:
        _no_file_error('Found %d possible files, not 1.' % len(possible_files))
        return 1
      gsfile_path = possible_files[0]
      file_name = os.path.basename(gsfile_path)

      # Download file to local machine.
      try:
        subprocess.call(['gsutil', 'cp', gsfile_path, folder_path])
      except subprocess.CalledProcessError:
        print ('gsutil error.  Try running this command outside of '
               'chroot?')
        output_str[board] = '%s: Could not run gsutil command.' % board
        return 1

      # Untar/rename files as needed.
      file_path = os.path.join(folder_path, file_name)
      if download_type == TEST:
        subprocess.call(['tar', '-xf', file_path, '-C', folder_path])
        os.remove(file_path)
      elif download_type == AUTOTEST:
        print '%s: running tar -xf command' % board
        subprocess.call(['tar', '-xf', file_path, '-C', folder_path])
        target_name = 'autotest'
        target_path = os.path.join(folder_path, file_name[:-len('.tar.bz2')],
                                   target_name)
        os.remove(file_path)
      elif download_type == FACTORY:
        print 'trying to unzip %s to %s' % (file_path, folder_path)
        subprocess.call(['unzip', '-q', file_path, '-d', folder_path])
        os.remove(file_path)
      else: # RECOVERY
        os.rename(file_path, os.path.join(folder_path, target_name))

    # Report successful download and return path to downloaded thing
    output_str[board] = target_path
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

  # Print output or run cros flash command.
  errors = ''
  if installing_one or installing_many:
    # Move to src/ dir to access 'cros' command.
    starting_dir = os.getcwd()
    os.chdir(src_dir)

    # Use 'cros flash' to copy images to boards.
    jobs = []
    for i in xrange(len(boards)):
      board = boards[i]
      # Skip unless board downloaded without errors.
      if not dl_error[board]:
        cmd = 'cros flash usb://%s ' + output_str[board]

        # Copy this (i-th) board to i-th drive
        if installing_one:
          # Use provided drive or leave blank.
          if arguments.to_stick:
            usb_drive = arguments.to_stick[i]
          else:
            usb_drive = ''
          cmd = cmd % usb_drive
          print 'Copying %s to %s.' % (board, usb_drive)
          proc = subprocess.Popen(cmd.split(' '))
          jobs.append(proc)

        # Copy this (only) board to all drives
        else:
          for usb_drive in arguments.to_many:
            cmd_per_usb = cmd % usb_drive
            print 'Copying %s to %s.' % (board, usb_drive)
            proc = subprocess.Popen(cmd_per_usb.split(' '))
            jobs.append(proc)

      else:
        errors += '%s\n' % output_str[board]

    # Wait for all copies to finish.
    for job in jobs:
      job.wait()
    if arguments.delete:
      print 'Deleting all files created for %s.' % board
      shutil.rmtree(dl_folder[board])

    # Return to previous directory.
    os.chdir(starting_dir)

  else:
    print '\nDownloaded File(s):'
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
