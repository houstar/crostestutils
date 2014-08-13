#!/usr/bin/python
#
# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''Utility functions for audio scripts.'''

import copy
import logging
import subprocess
import threading


AUTOTEST_GS_URL_FORMAT = 'gs://chromeos-autotest-results/%s/%s'

_popen_lock = threading.Lock()


class TestObject(object):
  '''Object for holding test data.'''

  def __init__(self, tag):
    self.tag = tag
    self.hostname = tag.split('/')[1]
    self.test_name = ''
    self.platform = ''
    self.release = ''
    self.build = ''
    self.perf_dict = {}

  @classmethod
  def parse(cls, line):
    '''Parse string of comma-separated fields into TestObject.

    The string to be parsed should be in comma-separated format:
      tag, platform, test_name, hostname, release, build, perf_dict

    Example:
      11932127-chromeos-test/chromeos4-row2-rack10-host6, link,
      audio_CrasLoopback, chromeos4-row2-rack10-host6, 37, 5914.0.0,
      rms_value: 0.668121
    '''
    values = [x.strip() for x in line.split(',')]
    test = cls(values[0])
    (test.platform, test.test_name, test.hostname, test.release,
     test.build) = values[1:6]
    test.perf_dict = dict(x.split(': ', 1) for x in values[6:])
    return test

  def __str__(self):
    return ', '.join(str(x) for x in (
        [self.tag, self.platform, self.test_name, self.hostname, self.release,
         self.build] +
        ['%s: %s' % item for item in self.perf_dict.iteritems()]))

  def __repr__(self):
    return str(self)

  def clone(self):
    return copy.copy(self)


def run_in_pool(functions, pool_size=8):
  lock = threading.Lock()

  def next_task():
    try:
      with lock:
        return next(functions)
    except StopIteration:
      return None

  def work():
    task = next_task()
    while task:
      task()
      task = next_task()

  threads = [threading.Thread(target=work) for _ in xrange(pool_size)]

  for t in threads:
    t.start()

  for t in threads:
    t.join()


def execute(args):
  with _popen_lock:
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  out, err = p.communicate()
  return out, err, p.wait()


def autotest_cat(job_tag, file_path):
  gs_url = AUTOTEST_GS_URL_FORMAT % (job_tag, file_path)
  out, err, ret = execute(['gsutil', 'cat', gs_url])
  if ret != 0:
    if 'InvalidUriError' in err:
      raise IOError(err)
    else:
      logging.error('command failed, return code: %d', ret)
      raise RuntimeError(err)
  return out
