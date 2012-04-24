#!/usr/bin/python
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deploy cros_gestures command line interface to test machine for usage.

Deploys the command line client and dependent libraries (gsutil and boto).
Package download/extract code loosely based on Autotest packaging utils.
"""

__author__ = 'truty@chromium.org (Mike Truty)'
__version__ = '1.0.0'


import logging
import optparse
import os
import shutil
import subprocess
import sys
import tempfile
import urlparse


LOG = logging.getLogger('cros_gestures')

GESTURES_INSTALL_DIR = '/usr/local/cros_gestures'
GESTURE_SERVER_URL = (
    'http://chromeos-gestures-valid.commondatastorage.googleapis.com/'
    'downloads/untrusted')
GESTURE_ARCHIVE = 'cros_gestures.tar.bz2'


class GestureInstallError(Exception):
    """The parent of all errors."""
    def __str__(self):
        return Exception.__str__(self) + _context_message(self)


class CmdError(GestureInstallError):
    """Raised when there is an error running a command"""


class PackageFetchError(GestureInstallError):
    """Raised when there is an error fetching the package"""


def RunCommand(cmd, dargs=None):
  """General command execution - based on replacing os.system()."""
  try:
      cmd = [cmd]
      if dargs:
          cmd += ['--%s=%s' % (k, v) for k, v in dargs.items()]
      logging.debug('Running command (%s)', cmd)
      retcode = subprocess.call(cmd, shell=True)
      if retcode < 0:
          LOG.error('Child command (%s) was terminated by signal -%s',
                    cmd, retcode)
      elif retcode > 0:
          LOG.error('Child command (%s) returned %s', cmd, retcode)
  except OSError, e:
      LOG.error('Execution failed:', str(e))
  return retcode


class HttpFetcher(object):
    """Downloads packages from a repository."""
    wget_cmd_pattern = 'wget --connect-timeout=15 -nv "%s" -O "%s"'


    def __init__(self, repository_url):
        """
        @param repository_url: The base URL of the http repository
        """
        self.url = repository_url


    def _QuickHttpTest(self):
        """ Run a simple 30 second wget on the repository to see if it is
        reachable. This avoids the need to wait for a full 10min timeout.
        """
        # just make a temp file to write a test fetch into
        temp_file = tempfile.NamedTemporaryFile()
        dest_file_path = temp_file.name

        try:
            # build up a wget command
            if self.url == GESTURE_SERVER_URL:
                parts = urlparse.urlparse(self.url)
                try_url = urlparse.urlunparse([parts.scheme, parts.netloc, '',
                                               None, None, None])
            else:
                try_url = self.url
            http_cmd = self.wget_cmd_pattern % (try_url, dest_file_path)
            try:
                if RunCommand(http_cmd, dargs={'timeout': 30}):
                    raise CmdError('Command failed')
            except Exception, e:
                msg = 'HTTP test failed, unable to contact %s: %s'
                raise PackageFetchError(msg % (try_url, e))
        finally:
            temp_file.close()


    def FetchPkgFile(self, filename, dest_path):
        logging.info('Fetching %s from %s to %s', filename, self.url,
                     dest_path)

        # do a quick test to verify the repo is reachable
        self._QuickHttpTest()

        # try to retrieve the package via http
        package_url = os.path.join(self.url, filename)
        try:
            cmd = self.wget_cmd_pattern % (package_url, os.path.join(dest_path,
                                                                     filename))
            result = RunCommand(cmd)
            if result or not os.path.isfile(os.path.join(dest_path, filename)):
                logging.error('wget failed: %s', result)
                raise CmdError('%s: %s', cmd, result)
            logging.debug('Successfully fetched %s from %s', filename,
                          package_url)
        except CmdError:
            # remove whatever junk was retrieved when the get failed
            RunCommand('rm -f %s/*' % dest_path)
            raise PackageFetchError('%s not found in %s' % (filename,
                                                            package_url))


def OutputAndExit(message):
    """Common error printing."""
    sys.stderr.write('%s\n' % message)
    sys.exit(1)


def UntarPkg(tarball_path, dest_dir):
    """Untar the downloaded package likely a .gz or .bz2."""
    RunCommand('tar xjf "%s" -C "%s"' % (tarball_path, dest_dir))


def VerifyInstallDirectory(force_option, path):
    """Ensure the target install directory is properly available."""
    if os.path.isdir(path):
        if not force_option:
            OutputAndExit('Directory (%s) for cros_gestures already exists. '
                          'Please use -F to override.' % path)
        LOG.debug('Removing existing cros_gestures now.')
        shutil.rmtree(path)


def CopyPackage(repo_url, package_name, install_dir):
    """Easy copy of package if it is already present."""
    source_file_name = os.path.join(repo_url, package_name)
    target_file_name = os.path.join(install_dir, package_name)
    if os.path.isfile(source_file_name):
        shutil.copyfile(source_file_name, target_file_name)
    return not os.path.isfile(target_file_name)


def DownloadPackage(repo_url, package_name, install_dir):
    """Download a package."""
    fetcher = HttpFetcher(repo_url)
    fetcher.FetchPkgFile(package_name, install_dir)


def InstallPackage(source_dir, package_name, install_dir):
    """Install our downloaded package."""
    UntarPkg(os.path.join(source_dir, package_name), source_dir)
    shutil.copytree(os.path.join(source_dir, 'cros_gestures'), install_dir)


def DownloadAndInstall(repo_url, package_name, install_dir):
    """Download and install a package."""
    temp_dir = tempfile.mkdtemp()
    try:
        if CopyPackage(repo_url, package_name, temp_dir):
            DownloadPackage(repo_url, package_name, temp_dir)
        InstallPackage(temp_dir, package_name, install_dir)
        logging.info('Installed to %s', install_dir)
        result = 0
    except PackageFetchError:
        logging.debug('%s could not be fetched from %s', package_name, repo_url)
        result = -1
    shutil.rmtree(temp_dir)
    return result


def parse_args(argv):
    """Process command line options."""
    usage_string = (
        'install_cros_gestures [options]\n\n'
        'Retrieves and installs all dependent packages for the cros_gestures '
        'developer/tester command line client tool.\n'
        'Run install_cros_gestures -h to see options.')
    parser = optparse.OptionParser(usage=usage_string)
    parser.add_option('-F', '--force',
                      help='Force install by replacing [default: %default]',
                      dest='forceoverwrite',
                      action='store_true',
                      default=False)
    parser.add_option('-D', '--detailed-debug',
                      help='Show even more output [default: %default]',
                      dest='detaileddebugout',
                      action='store_true',
                      default=False)
    parser.add_option('-s', '--server-url',
                      help='url for server downloads dir [default: %default]',
                      dest='serverurl',
                      default=GESTURE_SERVER_URL)
    options, args = parser.parse_args()
    if options.detaileddebugout:
        logging_level = logging.DEBUG
    else:
        logging_level = logging.INFO
    logging.basicConfig(level=logging_level)

    if len(args) > 0:
        OutputAndExit('No arguments are expected to be passed.\n\n%s' %
                      usage_string)

    return options


def main():
    """Logic of install."""
    options = parse_args(sys.argv)

    VerifyInstallDirectory(options.forceoverwrite, GESTURES_INSTALL_DIR)
    if DownloadAndInstall(options.serverurl, GESTURE_ARCHIVE,
                          GESTURES_INSTALL_DIR):
        LOG.info('Unable to find and install %s.', GESTURE_ARCHIVE)


if __name__ == '__main__':
    main()
