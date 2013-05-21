#!/usr/sbin/python
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import download_test_build
import os
import unittest

"""
This test can be used to download multiple test images using
download_test_build.
"""


class TestBuilds(unittest.TestCase):
      channel = 'dev'
      branch = 'R28'
      version = '4100.17.0'
      image = []

      def setUp(self):
          self.build = download_test_build.download_image()

      def tearDown(self):
          """Remove all test paths."""
#         disabled by default
#          for path in self.image:
#              print 'Removing the download %s' % path
#              os.remove(path)

      def test_daisy(self):
          """Test downloading daisy."""
          path = self.build.download(channel=self.channel,
                                     device='daisy', branch=self.branch,
                                     version=self.version)
          self.image.append(path)
          self.failUnless(os.path.exists(path))


      def test_link(self):
          """Test downloading link."""
          path = self.build.download(channel=self.channel,
                                     device='link', version=self.version,
                                     branch=self.branch)
          self.image.append(path)
          self.failUnless(os.path.exists(path))


      def test_parrot(self):
          """Test downloading parrot."""
          path = self.build.download(channel=self.channel,
                                     device='parrot', branch=self.branch,
                                     version=self.version)
          self.image.append(path)
          self.failUnless(os.path.exists(path))

if __name__ == '__main__':
    unittest.main()
