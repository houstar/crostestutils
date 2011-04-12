# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing methods/classes related to running parallel test jobs."""

import multiprocessing
import sys
import time

import cros_build_lib as cros_lib

class ParallelJobTimeoutError(Exception):
  """Thrown when a job ran for longer than expected."""
  pass


class ParallelJob(multiprocessing.Process):
  """Small wrapper for Process that stores output of its target method."""

  MAX_TIMEOUT_SECONDS = 1800
  SLEEP_TIMEOUT_SECONDS = 180

  def __init__(self, starting_semaphore, target, args):
    """Initializes an instance of a job.

    Args:
      starting_semaphore: Semaphore used by caller to wait on such that
        there isn't more than a certain number of parallel_jobs running.  Should
        be initialized to a value for the number of parallel_jobs wanting to be
        run at a time.
      target:  The func to run.
      args:  Args to pass to the fun.
    """
    super(ParallelJob, self).__init__(target=target, args=args)
    self._target = target
    self._args = args
    self._starting_semaphore = starting_semaphore

  def run(self):
    """Thread override.  Runs the method specified and sets output."""
    try:
      self._target(*self._args)
    finally:
      self._starting_semaphore.release()

  @classmethod
  def WaitUntilJobsComplete(cls, parallel_jobs):
    """Waits until all parallel_jobs have completed before returning.

    Given an array of parallel_jobs, returns once all parallel_jobs have
    completed or a max timeout is reached.

    Raises:
      ParallelJobTimeoutError:  if max timeout is reached.
    """
    def GetCurrentActiveCount():
      """Returns the (number of active jobs, first active job)."""
      active_count = 0
      active_job = None
      for parallel_job in parallel_jobs:
        if parallel_job.is_alive():
          active_count += 1
          if not active_job:
            active_job = parallel_job

      return (active_count, parallel_job)

    start_time = time.time()
    while (time.time() - start_time) < cls.MAX_TIMEOUT_SECONDS:
      (active_count, active_job) = GetCurrentActiveCount()
      if active_count == 0:
        return
      else:
        print >> sys.stderr, (
            'Process Pool Active: Waiting on %d/%d jobs to complete' %
            (active_count, len(parallel_jobs)))
        active_job.join(cls.SLEEP_TIMEOUT_SECONDS)
        time.sleep(5) # Prevents lots of printing out as job is ending.

    for parallel_job in parallel_jobs:
      if parallel_job.is_alive():
        parallel_job.terminate()

    raise ParallelJobTimeoutError('Exceeded max time of %d seconds to wait for '
                                  'job completion.' % cls.MAX_TIMEOUT_SECONDS)

  def __str__(self):
    return '%s(%s)' % (self._target, self._args)


def RunParallelJobs(number_of_simultaneous_jobs, jobs, jobs_args):
  """Runs set number of specified jobs in parallel.

  Note that there is a bug in Python Queue implementation that doesn't
  allow arbitrary sizes to be returned.  Instead, the process will just
  appear to have hung.  Be careful when accepting output.

  Args:
    number_of_simultaneous_jobs:  Max number of parallel_jobs to be run in
      parallel.
    jobs:  Array of methods to run.
    jobs_args:  Array of args associated with method calls.
  Returns:
    Returns an array of results corresponding to each parallel_job's output.
  """
  def ProcessOutputWrapper(func, args, output_queue):
    """Simple function wrapper that puts the output of a function in a queue."""
    try:
      output_queue.put(func(*args))
    except:
      output_queue.put(None)
      raise
    finally:
      output_queue.close()

  assert len(jobs) == len(jobs_args), 'Length of args array is wrong.'
  # Cache sudo access.
  cros_lib.RunCommand(['sudo', 'echo', 'Caching sudo credentials'],
                      print_cmd=False, redirect_stdout=True,
                      redirect_stderr=True)

  parallel_jobs = []
  output_array = []

  # Semaphore used to create a Process Pool.
  job_start_semaphore = multiprocessing.Semaphore(number_of_simultaneous_jobs)

  # Create the parallel jobs.
  for job, args in map(lambda x, y: (x, y), jobs, jobs_args):
    output = multiprocessing.Queue()
    parallel_job = ParallelJob(job_start_semaphore,
                               target=ProcessOutputWrapper,
                               args=(job, args, output))
    parallel_jobs.append(parallel_job)
    output_array.append(output)

  # We use a semaphore to ensure we don't run more jobs than required.
  # After each parallel_job finishes, it releases (increments semaphore).
  for next_parallel_job in parallel_jobs:
    job_start_semaphore.acquire(block=True)
    next_parallel_job.start()

  ParallelJob.WaitUntilJobsComplete(parallel_jobs)
  return [output.get() for output in output_array]
