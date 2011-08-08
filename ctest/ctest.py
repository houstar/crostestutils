#!/usr/bin/python
#
# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wrapper for tests that are run on builders."""

import fileinput
import optparse
import os
import re
import sys
import traceback
import urllib
import HTMLParser

import constants
sys.path.append(constants.SOURCE_ROOT)
import chromite.lib.cros_build_lib as cros_lib

_IMAGE_TO_EXTRACT = 'chromiumos_test_image.bin'
_NEW_STYLE_VERSION = '0.9.131.0'

class CrosImageDoesNotExistError(Exception):
  """Error thrown when no image can be found."""
  pass


class HTMLDirectoryParser(HTMLParser.HTMLParser):
  """HTMLParser for parsing the default apache file index."""

  def __init__(self, regex):
    HTMLParser.HTMLParser.__init__(self)
    self.regex_object = re.compile(regex)
    self.link_list = []

  def handle_starttag(self, tag, attrs):
    """Overrides from HTMLParser and is called at the start of every tag.

    This implementation grabs attributes from links (i.e. <a ... > </a>
    and adds the target from href=<target> if the <target> matches the
    regex given at the start.
    """
    if not tag.lower() == 'a':
      return

    for attr in attrs:
      if not attr[0].lower() == 'href':
        continue

      match = self.regex_object.match(attr[1])
      if match:
        self.link_list.append(match.group(0).rstrip('/'))


def ModifyBootDesc(download_folder, redirect_file=None):
  """Modifies the boot description of a downloaded image to work with path.

  The default boot.desc from another system is specific to the directory
  it was created in.  This modifies the boot description to be compatiable
  with the download folder.

  Args:
    download_folder: Absoulte path to the download folder.
    redirect_file:  For testing.  Where to copy new boot desc.
  """
  boot_desc_path = os.path.join(download_folder, 'boot.desc')
  in_chroot_folder = cros_lib.ReinterpretPathForChroot(download_folder)

  for line in fileinput.input(boot_desc_path, inplace=1):
    # Has to be done here to get changes to sys.stdout from fileinput.input.
    if not redirect_file:
      redirect_file = sys.stdout
    split_line = line.split('=')
    if len(split_line) > 1:
      var_part = split_line[0]
      potential_path = split_line[1].replace('"', '').strip()

      if potential_path.startswith('/home') and not 'output_dir' in var_part:
        new_path = os.path.join(in_chroot_folder,
                                os.path.basename(potential_path))
        new_line = '%s="%s"' % (var_part, new_path)
        cros_lib.Info('Replacing line %s with %s' % (line, new_line))
        redirect_file.write('%s\n' % new_line)
        continue
      elif 'output_dir' in var_part:
        # Special case for output_dir.
        new_line = '%s="%s"' % (var_part, in_chroot_folder)
        cros_lib.Info('Replacing line %s with %s' % (line, new_line))
        redirect_file.write('%s\n' % new_line)
        continue

    # Line does not need to be modified.
    redirect_file.write(line)

  fileinput.close()


def _GreaterVersion(version_a, version_b):
  """Returns the higher version number of two version number strings."""
  version_regex = re.compile('.*(\d+)\.(\d+)\.(\d+)\.(\d+).*')
  version_a_tokens = version_regex.match(version_a).groups()
  version_b_tokens = version_regex.match(version_b).groups()
  for i in range(4):
    (a, b) = (int(version_a_tokens[i]), int(version_b_tokens[i]))
    if a != b:
      if a > b: return version_a
      return version_b
  return version_a


def GetLatestLinkFromPage(url, regex):
  """Returns the latest link from the given url that matches regex.

  Args:
    url: Url to download and parse.
    regex: Regular expression to match links against.
  Raises:
    CrosImageDoesNotExistError if no image found using args.
  """
  url_file = urllib.urlopen(url)
  url_html = url_file.read()

  url_file.close()

  # Parses links with versions embedded.
  url_parser = HTMLDirectoryParser(regex=regex)
  url_parser.feed(url_html)
  try:
    return reduce(_GreaterVersion, url_parser.link_list)
  except TypeError:
    raise CrosImageDoesNotExistError('No image found at %s' % url)


def GetNewestLinkFromZipBase(board, channel, zip_server_base):
  """Returns the url to the newest image from the zip server.

  Args:
    board: board for the image zip.
    channel: channel for the image zip.
    zip_server_base:  base url for zipped images.
  Raises:
    CrosImageDoesNotExistError if no image found using args.
  """
  zip_base = os.path.join(zip_server_base, channel, board)
  latest_version = GetLatestLinkFromPage(zip_base, '\d+\.\d+\.\d+\.\d+/')

  zip_dir = os.path.join(zip_base, latest_version)
  zip_name = GetLatestLinkFromPage(zip_dir,
                                   'ChromeOS-\d+\.\d+\.\d+\.\d+-.*\.zip')
  return os.path.join(zip_dir, zip_name)


def GetLatestZipUrl(board, channel, zip_server_base):
  """Returns the url of the latest image zip for the given arguments.

  If the latest does not exist, tries to find the rc equivalent.  If neither
  exist, returns None.

  Args:
    board: board for the image zip.
    channel: channel for the image zip.
    zip_server_base:  base url for zipped images.
  """
  try:
    return GetNewestLinkFromZipBase(board, channel, zip_server_base)
  except CrosImageDoesNotExistError as ce:
    cros_lib.Warning(str(ce))
  try:
    return GetNewestLinkFromZipBase(board + '-rc', channel, zip_server_base)
  except CrosImageDoesNotExistError as ce:
    cros_lib.Warning(str(ce))
    return None


def GrabZipAndExtractImage(zip_url, download_folder, image_name) :
  """Downloads the zip and extracts the given image.

  Doesn't re-download if matching version found already in download folder.
  Args:
    zip_url - url for the image.
    download_folder - download folder to store zip file and extracted images.
    image_name - name of the image to extract from the zip file.
  """
  zip_path = os.path.join(download_folder, 'image.zip')
  versioned_url_path = os.path.join(download_folder, 'download_url')
  found_cached = False

  if os.path.exists(versioned_url_path):
    fh = open(versioned_url_path)
    version_url = fh.read()
    fh.close()

    if version_url == zip_url and os.path.exists(os.path.join(download_folder,
                                                 image_name)):
      cros_lib.Info('Using cached %s' % image_name)
      found_cached = True

  if not found_cached:
    cros_lib.Info('Downloading %s' % zip_url)
    cros_lib.RunCommand(['rm', '-rf', download_folder], print_cmd=False)
    os.mkdir(download_folder)
    urllib.urlretrieve(zip_url, zip_path)

    # Using unzip because python implemented unzip in native python so
    # extraction is really slow.
    cros_lib.Info('Unzipping image %s' % image_name)
    cros_lib.RunCommand(['unzip', '-d', download_folder, zip_path],
               print_cmd=False, error_message='Failed to download %s' % zip_url)

    ModifyBootDesc(download_folder)

    # Put url in version file so we don't have to do this every time.
    fh = open(versioned_url_path, 'w+')
    fh.write(zip_url)
    fh.close()

  version = zip_url.split('/')[-2]
  if not _GreaterVersion(version, _NEW_STYLE_VERSION) == version:
    # If the version isn't ready for new style, touch file to use old style.
    old_style_touch_path = os.path.join(download_folder, '.use_e1000')
    fh = open(old_style_touch_path, 'w+')
    fh.close()


def GeneratePublicKey(private_key_path):
  """Returns the path to a newly generated public key from given private key."""
  # Just output to local directory.
  public_key_path = 'public_key.pem'
  cros_lib.Info('Generating public key from private key.')
  cros_lib.RunCommand(['/usr/bin/openssl',
                       'rsa',
                       '-in', private_key_path,
                       '-pubout',
                       '-out', public_key_path,
                      ], print_cmd=False)
  return public_key_path



def RunAUTestHarness(board, channel, zip_server_base,
                     no_graphics, type, remote, clean, target_image,
                     test_results_root):
  """Runs the auto update test harness.

  The auto update test harness encapsulates testing the auto-update mechanism
  for the latest image against the latest official image from the channel.  This
  also tests images with suite_Smoke (built-in as part of its verification
  process).

  Args:
    board: the board for the latest image.
    channel: the channel to run the au test harness against.
    zip_server_base:  base url for zipped images.
    no_graphics: boolean - If True, disable graphics during vm test.
    type: which test harness to run.  Possible values: real, vm.
    remote: ip address for real test harness run.
    clean: Clean the state of test harness before running.
    target_image: Target image to test.
    test_results_root: Root directory to store au_test_harness results.
  """
  crosutils_root = os.path.join(constants.SOURCE_ROOT, 'src', 'scripts')

  if target_image is None:
    # Grab the latest image we've built.
    return_object = cros_lib.RunCommand(
      ['./get_latest_image.sh', '--board=%s' % board], cwd=crosutils_root,
      redirect_stdout=True, print_cmd=True)

    latest_image_dir = return_object.output.strip()
    target_image = os.path.join(latest_image_dir, _IMAGE_TO_EXTRACT)

  # Grab the latest official build for this board to use as the base image.
  # If it doesn't exist, run the update test against itself.
  download_folder = os.path.abspath('latest_download')
  zip_url = GetLatestZipUrl(board, channel, zip_server_base)

  base_image = None
  if zip_url:
    GrabZipAndExtractImage(zip_url, download_folder, _IMAGE_TO_EXTRACT)
    base_image = os.path.join(download_folder, _IMAGE_TO_EXTRACT)
  else:
    base_image = target_image

  update_engine_path = os.path.join(crosutils_root, '..', 'platform',
                                    'update_engine')

  if clean:
    private_key_path = os.path.join(update_engine_path, 'unittest_key.pem')
    public_key_path = GeneratePublicKey(private_key_path)

  cmd = ['bin/cros_au_test_harness',
         '--base_image=%s' % base_image,
         '--target_image=%s' % target_image,
         '--board=%s' % board,
         '--type=%s' % type,
         '--remote=%s' % remote,
         ]
  if test_results_root: cmd.append('--test_results_root=%s' % test_results_root)
  if no_graphics: cmd.append('--no_graphics')
  # Using keys is only compatible with clean.
  if clean:
    cmd.append('--clean')
    cmd.append('--private_key=%s' % private_key_path)
    cmd.append('--public_key=%s' % public_key_path)

  cros_lib.RunCommand(cmd, cwd=crosutils_root)


def main():
  parser = optparse.OptionParser()
  parser.add_option('-b', '--board',
                    help='board for the image to compare against.')
  parser.add_option('-c', '--channel',
                    help='channel for the image to compare against.')
  parser.add_option('--cache', default=False, action='store_true',
                    help='Cache payloads')
  parser.add_option('-z', '--zipbase',
                    help='Base url for hosted images.')
  parser.add_option('--no_graphics', action='store_true', default=False,
                    help='Disable graphics for the vm test.')
  parser.add_option('--target_image', default=None,
                    help='Target image to test.')
  parser.add_option('--test_results_root', default=None,
                    help='Root directory to store test results.  Should '
                         'be defined relative to chroot root.')
  parser.add_option('--type', default='vm',
                    help='type of test to run: [vm, real]. Default: vm.')
  parser.add_option('--remote', default='0.0.0.0',
                    help='For real tests, ip address of the target machine.')

  # Set the usage to include flags.
  parser.set_usage(parser.format_help())
  (options, args) = parser.parse_args()

  if args: parser.error('Extra args found %s.' % args)
  if not options.board: parser.error('Need board for image to compare against.')
  if not options.channel: parser.error('Need channel e.g. dev-channel.')
  if not options.zipbase: parser.error('Need zip url base to get images.')

  RunAUTestHarness(options.board, options.channel, options.zipbase,
                   options.no_graphics, options.type, options.remote,
                   not options.cache, options.target_image,
                   options.test_results_root)


if __name__ == '__main__':
  main()

