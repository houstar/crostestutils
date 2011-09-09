#!/usr/bin/python
#
# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""GenerateTestPayloads 'quickly' creates payloads needed for testing."""

import logging
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
import cros_build_lib as cros_lib

from crostestutils.au_test_harness import cros_au_test_harness
from crostestutils.generate_test_payloads import payload_generation_exception
from crostestutils.lib import dev_server_wrapper
from crostestutils.lib import parallel_test_job
from crostestutils.lib import public_key_manager
from crostestutils.lib import test_helper


class UpdatePayload(object):
  """Defines an update payload."""

  def __init__(self, target, base, key=None):
    self.base = base
    self.target = target
    self.key = key

  def __str__(self):
    my_repr = self.target
    if self.base:
      my_repr = self.base + '->' + my_repr

    if self.key:
      my_repr = my_repr + '+' + self.key

    return my_repr

  def __eq__(self, other):
    return str(self) == str(other)

  def __hash__(self):
    return hash(str(self))


class UpdatePayloadGenerator(object):
  """Class responsible for generating update payloads."""

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
    self.full_suite = options.full_suite
    self.payloads = set([])
    self.nplus1 = options.nplus1
    self.vm = options.vm

  def _AddUpdatePayload(self, target, base, key=None):
    """Adds a new required update payload.  If base is None, a full payload."""
    self.payloads.add(UpdatePayload(target, base, key))

  def GenerateImagesForTesting(self):
    # All vm testing requires a VM'ized target.
    if self.vm: self.target = test_helper.CreateVMImage(self.target, self.board)

    if self.full_suite:
      if self.public_key:
        self.target_signed = self.target + '.signed'
        if not os.path.exists(self.target_signed):
          logging.info('Creating a signed image for signed payload test.')
          shutil.copy(self.target, self.target_signed)

        public_key_manager.PublicKeyManager(self.target_signed,
                                            self.public_key).AddKeyToImage()

      self.base = test_helper.CreateVMImage(self.base, self.board)

  def GeneratePayloadRequirements(self):
    """Generate Payload Requirements for AUTestHarness and NPlus1 Testing."""

    def AddPayloadsForAUTestHarness():
      if self.full_suite:
        self._AddUpdatePayload(self.target_no_vm, self.base)
        self._AddUpdatePayload(self.base_no_vm, self.target_no_vm)
        self._AddUpdatePayload(self.target_no_vm, self.target)

        # Need a signed payload for the signed payload test.
        if self.target_signed:
          self._AddUpdatePayload(self.target_no_vm, self.target_signed,
                                 self.private_key)
      else:
        self._AddUpdatePayload(self.target_no_vm, self.target)

    def AddNPlus1Updates():
      self._AddUpdatePayload(self.target_no_vm, self.base_no_vm)
      self._AddUpdatePayload(self.target_no_vm, self.target_no_vm)
      self._AddUpdatePayload(self.target_no_vm, None)

    AddPayloadsForAUTestHarness()
    if self.nplus1: AddNPlus1Updates()

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
      command = ['sudo', 'start_devserver', '--pregenerate_update', '--exit']

      in_chroot_key = None
      in_chroot_base = None
      in_chroot_target = cros_lib.ReinterpretPathForChroot(payload.target)
      if payload.base:
        in_chroot_base = cros_lib.ReinterpretPathForChroot(payload.base)

      if payload.key:
        in_chroot_key = cros_lib.ReinterpretPathForChroot(payload.key)

      command.append('--image=%s' % in_chroot_target)
      if payload.base: command.append('--src_image=%s' % in_chroot_base)
      if self.vm: command.append('--for_vm')
      if payload.key: command.append('--private_key=%s' % in_chroot_key)

      debug_message = 'delta payload from %s to %s' % (payload.base,
                                                       payload.target)

      if in_chroot_key:
        debug_message = 'Generating a signed %s' % debug_message
      else:
        debug_message = 'Generating an unsigned %s' % debug_message

      logging.info(debug_message)
      return cros_lib.RunCommand(command, enter_chroot=True, print_cmd=False,
                                 cwd=cros_lib.GetCrosUtilsPath(),
                                 log_to_file=log_file, error_ok=True,
                                 exit_code=True)

    def ProcessOutput(log_files, return_codes):
      """Processes results from the log files of GeneratePayload invocations.

      Args:
        log_files:  A list of filename strings with stored logs.
        return_codes: An equally sized list of return codes pertaining to
          the processes that ran that generated those logs.
      Returns:
        An array of cache entries from the log files.
      """
      # Looking for this line in the output.
      key_line_re = re.compile('^PREGENERATED_UPDATE=([\w/./+]+)')
      return_array = []
      for log_file, return_code in zip(log_files, return_codes):
        with open(log_file) as log_file_handle:
          output = log_file_handle.read()

        if return_code != 0:
          logging.error(output)
          raise payload_generation_exception.PayloadGenerationException(
              'Failed to generate a required update.')
        else:
          for line in output.splitlines():
            match = key_line_re.search(line)
            if match:
              # Convert blah/blah/update.gz -> update/blah/blah.
              path_to_update_gz = match.group(1).rstrip()
              path_to_update_dir = path_to_update_gz.rpartition(
                  '/update.gz')[0]

              # Check that we could actually parse the directory correctly.000
              if not path_to_update_dir:
                raise payload_generation_exception.PayloadGenerationException(
                    'Payload generated but failed to parse cache directory.')

              return_array.append('/'.join(['update', path_to_update_dir]))
              break
          else:
            logging.error('Could not find update string in log.')

      return return_array

    update_ids = []
    jobs = []
    args = []
    log_files = []
    for payload in self.payloads:
      fd, log_file = tempfile.mkstemp('GenerateVMUpdate')
      os.close(fd)  # Just want filename so close file immediately.

      update_id = dev_server_wrapper.GenerateUpdateId(
          payload.target, payload.base, payload.key)
      update_ids.append(update_id)
      jobs.append(GeneratePayload)
      args.append((payload, log_file))
      log_files.append(log_file)

    logging.info('Generating updates required for this test suite in parallel.')
    error_codes = parallel_test_job.RunParallelJobs(
        test_helper.CalculateDefaultJobs(), jobs, args)
    results = ProcessOutput(log_files, error_codes)

    # Build the dictionary from our id's and returned cache paths.
    cache_dictionary = {}
    for index, update_id in enumerate(update_ids):
      cache_dictionary[update_id] = results[index]

    return cache_dictionary

  def DumpCacheToDisk(self, cache):
    """Dumps the cache to the same folder as the images."""
    path_to_dump = os.path.dirname(self.target)
    cache_file = os.path.join(path_to_dump, cros_au_test_harness.CACHE_FILE)

    logging.info('Dumping %s', cache_file)
    with open(cache_file, 'w') as file_handle:
      pickle.dump(cache, file_handle)


def CheckOptions(parser, options):
  """Checks that given options are valid.

  Args:
    parser: Parser used to parse options.
    options:  Parse options from OptionParser.
  """
  if not options.target or not os.path.isfile(options.target):
    parser.error('Target image must exist.')

  if not options.base:
    logging.info('Base image not specified. Using target as base image.')
    options.base = options.target

  if not os.path.isfile(options.base):
    parser.error('Base image must exist.')

  if options.private_key:
    if not os.path.isfile(options.private_key):
      parser.error('Private key must exist.')

    if not os.path.isfile(options.public_key):
      parser.error('Public key must exist.')

  if options.vm:
    if not options.board:
      parser.error('Board must be set to generate update '
                   'payloads for vm.')


def main():
  test_helper.SetupCommonLoggingFormat()
  parser = optparse.OptionParser()
  parser.add_option('--base', help='Image we want to test updates from.')
  parser.add_option('--board', help='Board used for the images.')
  parser.add_option('--clean', default=False, dest='clean', action='store_true',
                    help='Clean cache of previous payloads')
  parser.add_option('--full_suite', default=False, action='store_true',
                    help='Prepare to run the full au test suite.')
  parser.add_option('--novm', default=True, action='store_false', dest='vm',
                    help='Test Harness payloads will not be tested in a VM.')
  parser.add_option('--nplus1', default=False, action='store_true',
                    help='Produce nplus1 updates for testing in lab.')
  parser.add_option('--private_key',
                    help='Private key to sign payloads.')
  parser.add_option('--public_key',
                    help='Public key to verify signed payloads.')
  parser.add_option('--target', help='Image we want to test updates to.')
  options = parser.parse_args()[0]
  CheckOptions(parser, options)

  if options.clean:
    dev_server_wrapper.DevServerWrapper.WipePayloadCache()

  generator = UpdatePayloadGenerator(options)
  generator.GenerateImagesForTesting()
  generator.GeneratePayloadRequirements()
  cache = generator.GeneratePayloads()
  generator.DumpCacheToDisk(cache)


if __name__ == '__main__':
  main()
