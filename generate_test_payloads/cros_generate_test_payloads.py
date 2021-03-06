#!/usr/bin/python2
#
# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module generates update payloads for testing in parallel.

This module generates update payloads in parallel using the devserver. After
running this module, test payloads are generated and left in the devserver
cache. In addition, this module produces a serialized dictionary stored
with the target image that contains a mapping from the update payload name
to the path it is stored in the devserver cache.  This dictionary can then be
used by other testing scripts i.e. au_test_harness, to locate and use these
payloads for testing in virtual machines.

FOR USE OUTSIDE CHROOT ONLY.
"""

from __future__ import print_function

import functools
import optparse
import os
import pickle
import re
import shutil
import sys
import tempfile

import constants
sys.path.append(constants.CROSUTILS_LIB_DIR)
sys.path.append(constants.CROS_PLATFORM_ROOT)
sys.path.append(constants.SOURCE_ROOT)

from chromite.lib import cros_build_lib
from chromite.lib import cros_logging as logging
from chromite.lib import dev_server_wrapper
from chromite.lib import locking
from chromite.lib import osutils
from chromite.lib import parallel
from chromite.lib import path_util
from chromite.lib import sudo
from chromite.lib import timeout_util
from crostestutils.au_test_harness import cros_au_test_harness
from crostestutils.generate_test_payloads import payload_generation_exception
from crostestutils.lib import image_extractor
from crostestutils.lib import public_key_manager
from crostestutils.lib import test_helper


class InvalidDevserverOutput(Exception):
  """If we are unable to parse devserver output, this is raised."""


class UpdatePayload(object):
  """Wrapper around an update payload.

  This class defines an update payload that should be generated.  The only
  required variable to be set is |target|.  If the base image is set to None,
  this defines a full update payload to the target image.

  Variables:
    target: Payload to this image.
    base: If not None, a delta payload from this image.
    key: If set, signed payload using this private key.
    archive: If set, this payload should be archived.
    archive_stateful: If set and archive is set, archive the stateful tarball
      for the target image.
  """
  NAME_SPLITTER = '_'

  def __init__(self, target, base, key=None, archive=False,
               archive_stateful=False, for_vm=False):
    self.base = base
    self.target = target
    self.key = key
    self.archive = archive
    self.archive_stateful = archive_stateful
    self.for_vm = for_vm

  def GetNameForBin(self):
    """Returns the path we should name an archived payload."""
    real_target = os.path.realpath(self.target)
    board, target_os_version, _ = real_target.split('/')[-3:]
    prefix = 'chromeos'
    suffix = 'dev.bin'
    if self.base:
      real_base = os.path.realpath(self.base)
      base_os_version, _ = real_base.split('/')[-2:]
      name = self.NAME_SPLITTER.join([base_os_version, target_os_version, board,
                                      'delta'])
    else:
      name = self.NAME_SPLITTER.join([target_os_version, board, 'full'])

    return self.NAME_SPLITTER.join([prefix, name, suffix])

  def UpdateId(self):
    """Generates a unique update id the test harness can understand."""
    return dev_server_wrapper.GenerateUpdateId(self.target, self.base,
                                               self.key, self.for_vm)

  def __str__(self):
    my_repr = self.target
    if self.base:
      my_repr = self.base + '->' + my_repr

    if self.key:
      my_repr = my_repr + '+' + self.key

    if self.for_vm:
      my_repr = my_repr + '+' + 'for_vm'

    return my_repr

  def __eq__(self, other):
    return str(self) == str(other)

  def __hash__(self):
    return hash(str(self))


class UpdatePayloadGenerator(object):
  """Class responsible for generating update payloads."""
  CHROOT_PATH_TO_DEVSERVER_CACHE = 'var/lib/devserver/static/cache'

  def __init__(self, options):
    """Initializes a generator object from parsed options.

    Args:
      options: Parsed options from main().
    """
    self.target = options.target
    self.base = options.base
    self.target_signed = None  # Set later when creating the image.

    # For vm tests we use the _qemu name for the images.  Regardless of vm or
    # non vm, these no_vm names are guaranteed to be non-qemu base/target names.
    self.base_no_vm = self.base
    self.target_no_vm = self.target

    # Keys.
    self.public_key = options.public_key
    self.private_key = options.private_key

    # Affect what payloads we create.
    self.board = options.board
    self.basic_suite = options.basic_suite
    self.full_suite = options.full_suite
    self.payloads = set([])
    self.full_payload = options.full_payload
    self.nplus1_archive_dir = options.nplus1_archive_dir

    self.jobs = options.jobs
    self.nplus1 = options.nplus1

    self.vm = _ShouldGenerateVM(options)

  def _AddUpdatePayload(self, target, base, key=None, archive=False,
                        archive_stateful=False, for_vm=False):
    """Adds a new required update payload.  If base is None, a full payload."""
    self.payloads.add(UpdatePayload(target, base, key, archive,
                                    archive_stateful, for_vm))

  def GenerateImagesForTesting(self):
    # All vm testing requires a VM'ized target.
    if self.vm:
      self.target = test_helper.CreateVMImage(self.target, self.board)

    if self.full_suite:
      if self.public_key:
        self.target_signed = self.target + '.signed'
        if not os.path.exists(self.target_signed):
          logging.info('Creating a signed image for signed payload test.')
          shutil.copy(self.target, self.target_signed)

        public_key_manager.PublicKeyManager(self.target_signed,
                                            self.public_key).AddKeyToImage()

      # The full suite may not have a VM image produced for the test image yet.
      # Ensure this is created.
      self.base = test_helper.CreateVMImage(self.base, self.board)

  def GeneratePayloadRequirements(self):
    """Generate Payload Requirements for AUTestHarness and NPlus1 Testing."""
    if self.full_suite:
      # N-1->N.
      self._AddUpdatePayload(self.target, self.base, for_vm=self.vm)

      # N->N after N-1->N.
      self._AddUpdatePayload(self.target, self.target, for_vm=self.vm)

      # N->N From VM base.
      self._AddUpdatePayload(self.target, self.target, for_vm=self.vm)

      # Need a signed payload for the signed payload test.
      if self.target_signed:
        self._AddUpdatePayload(self.target_signed, self.target_signed,
                               self.private_key, for_vm=self.vm)

    if self.basic_suite:
      # Update image to itself from VM base.
      self._AddUpdatePayload(self.target, self.target, for_vm=self.vm)

    # Add deltas for m minus 1 to n and n to n.
    if self.nplus1:
      self._AddUpdatePayload(self.target_no_vm, self.base_no_vm, archive=True)
      self._AddUpdatePayload(self.target_no_vm, self.target_no_vm, archive=True)

    # Add the full payload.
    if self.nplus1 or self.full_payload:
      self._AddUpdatePayload(self.target_no_vm, None, archive=True,
                             archive_stateful=True)


  def GeneratePayloads(self):
    """Iterates through payload requirements and generates them.

    This is the main method of this class.  It iterates through payloads
    it needs, generates them, and builds a Cache that can be used by the
    test harness to reference these payloads.

    Returns:
      The cache as a Python dict.
    """

    def GeneratePayload(payload, log_file):
      """Returns the error code from generating an update with the devserver."""
      # Base command.
      command = ['start_devserver', '--pregenerate_update', '--exit']

      in_chroot_key = in_chroot_base = None
      in_chroot_target = path_util.ToChrootPath(payload.target)
      if payload.base:
        in_chroot_base = path_util.ToChrootPath(payload.base)

      if payload.key:
        in_chroot_key = path_util.ToChrootPath(payload.key)

      command.append('--image=%s' % in_chroot_target)
      if payload.base:
        command.append('--src_image=%s' % in_chroot_base)
      if payload.key:
        command.append('--private_key=%s' % in_chroot_key)

      if payload.base:
        debug_message = 'delta payload from %s to %s' % (payload.base,
                                                         payload.target)
      else:
        debug_message = 'full payload to %s' % payload.target

      if payload.for_vm:
        debug_message += ' and not patching the kernel.'

      if in_chroot_key:
        debug_message = 'Generating a signed %s' % debug_message
      else:
        debug_message = 'Generating an unsigned %s' % debug_message

      logging.info(debug_message)
      try:
        with timeout_util.Timeout(constants.MAX_TIMEOUT_SECONDS):
          cros_build_lib.SudoRunCommand(command, log_stdout_to_file=log_file,
                                        combine_stdout_stderr=True,
                                        enter_chroot=True, print_cmd=False,
                                        cwd=constants.SOURCE_ROOT)
      except (timeout_util.TimeoutError, cros_build_lib.RunCommandError):
        # Print output first, then re-raise the exception.
        if os.path.isfile(log_file):
          logging.error(osutils.ReadFile(log_file))
        raise

    def ProcessOutput(log_files):
      """Processes results from the log files of GeneratePayload invocations.

      Args:
        log_files: A list of filename strings with stored logs.

      Returns:
        An array of cache entries from the log files.

      Raises:
        payload_generation_exception.PayloadGenerationException: Raises this
          exception if we failed to parse the devserver output to find the
          location of the update path.
      """
      # Looking for this line in the output.
      key_line_re = re.compile(r'^PREGENERATED_UPDATE=([\w/./+]+)')
      return_array = []
      for log_file in log_files:
        with open(log_file) as f:
          for line in f:
            match = key_line_re.search(line)
            if match:
              # Convert cache/label/update.gz -> update/cache/label.
              path_to_update_gz = match.group(1).rstrip()
              path_to_update_dir = path_to_update_gz.rpartition(
                  '/update.gz')[0]

              # Check that we could actually parse the directory correctly.
              if not path_to_update_dir:
                raise payload_generation_exception.PayloadGenerationException(
                    'Payload generated but failed to parse cache directory.')

              return_array.append('/'.join(['update', path_to_update_dir]))
              break
          else:
            logging.error('Could not find PREGENERATED_UPDATE in log:')
            f.seek(0)
            for line in f:
              logging.error('  log: %s', line)
            # This is not a recoverable error.
            raise InvalidDevserverOutput('Could not parse devserver log')

      return return_array

    jobs = []
    log_files = []
    # Generate list of paylods and list of log files.
    for payload in self.payloads:
      fd, log_file = tempfile.mkstemp('GenerateVMUpdate')
      os.close(fd)  # Just want filename so close file immediately.

      jobs.append(functools.partial(GeneratePayload, payload, log_file))
      log_files.append(log_file)

    # Run update generation code and wait for output.
    logging.info('Generating updates required for this test suite in parallel.')
    try:
      parallel.RunParallelSteps(jobs, max_parallel=self.jobs)
    except parallel.BackgroundFailure as ex:
      logging.error(ex)
      raise payload_generation_exception.PayloadGenerationException(
          'Failed to generate a required update.')

    results = ProcessOutput(log_files)

    # Build the dictionary from our id's and returned cache paths.
    cache_dictionary = {}
    for index, payload in enumerate(self.payloads):
      # Path return is of the form update/cache/directory.
      update_path = results[index]
      cache_dictionary[payload.UpdateId()] = update_path
      # Archive payload to payload directory.
      if payload.archive and self.nplus1_archive_dir:
        # Only need directory as we know the rest.
        path_to_payload_dir = os.path.join(
            constants.SOURCE_ROOT, 'chroot',
            self.CHROOT_PATH_TO_DEVSERVER_CACHE, os.path.basename(update_path))
        payload_path = os.path.join(path_to_payload_dir, 'update.gz')
        archive_path = os.path.join(self.nplus1_archive_dir,
                                    payload.GetNameForBin())
        logging.info('Archiving %s to %s.', payload.GetNameForBin(),
                     archive_path)
        shutil.copyfile(payload_path, archive_path)
        if payload.archive_stateful:
          stateful_path = os.path.join(path_to_payload_dir, 'stateful.tgz')
          archive_path = os.path.join(self.nplus1_archive_dir, 'stateful.tgz')
          logging.info('Archiving stateful payload from %s to %s',
                       payload.GetNameForBin(), archive_path)
          shutil.copyfile(stateful_path, archive_path)

    return cache_dictionary

  def DumpCacheToDisk(self, cache):
    """Dumps the cache to the same folder as the images."""
    if not self.basic_suite and not self.full_suite:
      logging.info('Not dumping payload cache to disk as payloads for the '
                   'test harness were not requested.')
    else:
      path_to_dump = os.path.dirname(self.target)
      cache_file = os.path.join(path_to_dump, cros_au_test_harness.CACHE_FILE)

      logging.info('Dumping %s', cache_file)
      with open(cache_file, 'w') as file_handle:
        pickle.dump(cache, file_handle)


def _ShouldGenerateVM(options):
  """Returns true if we will need a VM version of our images."""
  # This is a combination of options.vm and whether or not we are generating
  # payloads for vm testing.
  return options.vm and (options.basic_suite or options.full_suite)


def CheckOptions(parser, options):
  """Checks that given options are valid.

  Args:
    parser: Parser used to parse options.
    options: Parse options from OptionParser.
  """
  if not options.target or not os.path.isfile(options.target):
    parser.error('Target image must exist.')

  # Determine the base image. If latest_from_config specified, find the latest
  # image from the given config. If it doesn't exist, use the target image.
  target_version = os.path.realpath(options.target).rsplit('/', 2)[-2]
  if options.base_latest_from_dir:
    # Extract the latest build.
    extractor = image_extractor.ImageExtractor(options.base_latest_from_dir,
                                               os.path.basename(options.target))
    latest_image_dir = extractor.GetLatestImage(target_version)
    if latest_image_dir:
      options.base = extractor.UnzipImage(latest_image_dir)
    else:
      logging.warning('No previous image.zip found in local archive.')

  if not options.base:
    logging.info('Using target image as base image.')
    options.base = options.target

  if not os.path.isfile(options.base):
    parser.error('Base image must exist.')

  if options.private_key:
    if not os.path.isfile(options.private_key):
      parser.error('Private key must exist.')

    if not os.path.isfile(options.public_key):
      parser.error('Public key must exist.')

  if _ShouldGenerateVM(options):
    if not options.board:
      parser.error('Board must be set to generate update '
                   'payloads for vm.')

  if options.full_payload or options.nplus1:
    if not options.nplus1_archive_dir:
      parser.error('Must specify an archive directory if nplus1 or '
                   'full payload are specified.')


def main():
  test_helper.SetupCommonLoggingFormat()
  parser = optparse.OptionParser()

  # Options related to which payloads to generate.
  parser.add_option('--basic_suite', default=False, action='store_true',
                    help='Prepare to run the basic au test suite.')
  parser.add_option('--full_suite', default=False, action='store_true',
                    help='Prepare to run the full au test suite.')
  parser.add_option('--full_payload', default=False, action='store_true',
                    help='Generate the full update payload and store it in '
                    'the nplus1 archive dir.')
  parser.add_option('--nplus1', default=False, action='store_true',
                    help='Produce nplus1 updates for testing in lab and store '
                    'them in the nplus1 archive dir.')
  parser.add_option('--nplus1_archive_dir', default=None,
                    help='Archive nplus1 updates into this directory.')

  # Options related to how to generate test payloads for the test harness.
  parser.add_option('--novm', default=True, action='store_false', dest='vm',
                    help='Test Harness payloads will not be tested in a VM.')
  parser.add_option('--private_key',
                    help='Private key to sign payloads for test harness.')
  parser.add_option('--public_key',
                    help='Public key to verify payloads for test harness.')

  # Options related to the images to test.
  parser.add_option('--board', help='Board used for the images.')
  parser.add_option('--base', help='Image we want to test updates from.')
  parser.add_option('--base_latest_from_dir', help='Ignore the base '
                    'option and use the latest image from the specified '
                    'directory as the base image. If none exists, default to '
                    'target image.')
  parser.add_option('--target', help='Image we want to test updates to.')

  # Miscellaneous options.
  parser.add_option('--jobs', default=test_helper.CalculateDefaultJobs(),
                    type=int,
                    help='Number of payloads to generate in parallel.')

  options = parser.parse_args()[0]
  CheckOptions(parser, options)
  if options.nplus1_archive_dir and not os.path.exists(
      options.nplus1_archive_dir):
    os.makedirs(options.nplus1_archive_dir)

  # Don't allow this code to be run more than once at a time.
  lock_path = os.path.join(os.path.dirname(__file__), '.lock_file')
  with locking.FileLock(lock_path, 'generate payloads lock') as lock:
    lock.write_lock()
    with sudo.SudoKeepAlive():
      generator = UpdatePayloadGenerator(options)
      generator.GenerateImagesForTesting()
      generator.GeneratePayloadRequirements()
      cache = generator.GeneratePayloads()
      generator.DumpCacheToDisk(cache)


if __name__ == '__main__':
  main()
