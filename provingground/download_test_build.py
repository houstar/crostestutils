#!/usr/bin/python
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import subprocess as sub
import sys
import xml.parsers.expat


"""
This script can be used to download chromeos test images from the the cloud
storage. We assume that the cloud storage path remains similar all the time.

eg: gs://chromeos-releases/dev-channel/link/4162.0.0/
    ChromeOS-R29-4162.0.0-link.zip

So passing the above value to 'gstuil cp ' will download
the relevant CrOS image.

After downloading the file we uzip the file and wait for the user
to give the path to which the image should be copied.

eg: /dev/sdb

This script will create a build_defaults.xml file with the defaults info in
the scripts folder. So please run this from a folder with a write permissions.

"""


def run_command(command, shell=False):
    """ Run a given command using subprocess.

    @param command: The command to run. Should be a list.
    @param shell: Flag to use bash to run the command.

    @return out: Output of the process.
    """
    process = sub.Popen(command, stdout=sub.PIPE,
                        stderr=sub.PIPE, shell=shell)
    (out, err) = process.communicate()

    if err and 'Copying gs://chromeos-releases/' not in err:
        raise Exception('We got an error %s' % err)
    return out


class defaults():
    # TODO: Have a defaults file to read/write into it.
    channel_list = ['dev', 'beta', 'stable']
    device_list = ['x86-mario', 'x86-zgb', 'x86-alex', 'daisy', 'stout',
                   'link', 'butterfly', 'stout', 'stumpy', 'parrot', 'lumpy',]
    default_dict = {'channel': None, 'device': None,
                    'branch': None, 'version': None}
    defaults_file = 'build_defaults.xml'


    def __init__(self):
        if not os.path.exists(self.defaults_file):
            self._create_defaults()


    def set_defaults(self, channel, device, version, branch):
        """Set the new defaults.

        @param channel: default channel to be saved.
        @param device: defalut device to be saved.
        @param version: default version to be saved.
        @param branch: default branch to be saved.
        """
        self.default_dict['channel'] = channel
        self.default_dict['branch'] = branch
        self.default_dict['version'] = version
        self.default_dict['device'] = device
        self._update_defaults()


    def _create_defaults_element(self, initial=True):
        """Create a defaults element to be added to the xml file.

        @param initial: Flag to check if we are creating or updating the
                        defaults.

        @return defaults_element: Element with defaults attributes to be added.
        """
        defaults_element = '<defaults '
        for key in self.default_dict.keys():
            if initial or self.default_dict[key]:
                defaults_element += '%s="%s" ' % (key, self.default_dict[key])
        defaults_element += ('></defaults>\n')
        return defaults_element


    def _update_defaults(self):
        """Update the defaults list in database/xml."""
        defaults_element = self._create_defaults_element(initial=False)
        lines = open(self.defaults_file, 'r').readlines()
        os.remove(self.defaults_file)
        fin = open(self.defaults_file, 'w')
        for line in lines:
            if '<defaults ' in line:
                fin.write(defaults_element)
                break  # this will always be the last line
            else:
                fin.write(line)
        fin.close()


    def _create_defaults(self):
        """Create all the defaults."""
        print 'Creating Defaults file.'
        fout = open(self.defaults_file, 'wb')
        root = '<feed xmlns=\'http://www.w3.org/2005/Atom\' xml:lang=\'en\'>\n'
        fout.write(root)
        channel_element = '<channel>'
        for channel in self.channel_list:
            channel_element += '%s, ' % channel
        channel_element += ('</channel>\n')
        fout.write(channel_element)
        device_element = '<device>'
        for device in self.device_list:
            device_element += '%s, ' % device
        device_element += ('</device>\n')
        fout.write(device_element)
        defaults_element = self._create_defaults_element()
        fout.write(defaults_element)
        fout.close()


    def previous_defaults(self):
        """Get the default values."""
        # Parse and read the xml data
        self.read_xml()
        return self.default_dict


    def start_element(self, name, attrs):
        if name == 'defaults':
            self.default_dict = attrs


    def char_data(self, data):
        if 'dev' in data:
            self.add_default_channel(data)
        if 'link' in data:
            self.add_default_devices(data)


    def read_xml(self):
        """Read and parse the xml file."""
        fin = open(self.defaults_file, 'r')
        parse_data = fin.read()
        parser = xml.parsers.expat.ParserCreate()
        parser.StartElementHandler = self.start_element
        parser.CharacterDataHandler = self.char_data
        parser.Parse(parse_data)


    def channel(self):
        """Read the default channel from the logs"""
        return self.channel_list


    def add_default_channel(self, data):
        """Add a channel if it does not exist in defaults."""
        for channel in data.split(','):
            if channel and (channel not in self.channel_list):
                self.channel_list.append(channel)


    def add_default_devices(self, data):
        """Add a device if it does not exist in defaults."""
        for device in data.split(','):
            if device and device not in self.device_list:
                self.device_list.append(device)


    def element_in_list(self, element, element_list):
        for old_element in element_list:
            if element in old_element:
                return False
        return True


class download_image():
    # This script will work until the image path remains unchanged. If the
    # cloud team decides to change the default path to the images, change this
    # path constant accordingly. This is used build_source.
    image_path = 'gs://chromeos-releases/%s-channel/%s/%s/ChromeOS-%s-%s-%s.zip'

    def file_check(self, dest, folder=True, action=False):
        """ Check if a file or folder exists.
        This is used in two places, first to check if we have the test
        folder and second to check if we already have the file to download.

        @param dest: The path to look for. Should be a string.
        @param folder: Flag to indicate if the path is a directory or not.
        @param action: Flag to indicate if an action is required.
                       eg: Creation or deletion.
        """
        if folder and not os.path.exists(dest):
           if action:
               os.makedirs(dest)
               print 'Created directory %s' % dest
           else:
               raise Exception('The path %s does not exist' % dest)
        elif folder and not os.path.isdir(dest):
           raise Exception('The path %s exists and is not a folder.' % dest)
        elif not folder and os.path.exists(dest):
           zip_file = os.path.basename(dest)
           file_type = 'file'
           if os.path.isdir(zip_file):
              file_type = 'folder'
           if action:
               print ('The %s %s exists or is downloaded in %s' %
                     (os.path.basename(dest), file_type, os.path.dirname(dest)))
               delete_flag = raw_input('Do you want to remove the existing?'
                                       ' (Y/N): ')
               if delete_flag.lower() == 'y':
                   print 'Removing the file %s' % dest
                   os.remove(dest)
               else:
                   print 'Continuing with the download.'


    def check_download(self, dest, source):
        """Check if the download was successful. Verify the checksum and the
           size of the downloaded file.

        @param dest:   The complete path to the downloaded file
        @param source: The complete path to the file in cloudstorage.
        """
        out = run_command(['gsutil', 'ls', '-L', source])
        checksum = size = ''
        for line in out.split('\n'):
            if 'ETag:' in line:
                checksum = line.split(':')[1].strip('\t')
            elif 'Content-Length:' in line:
                size = line.split(':')[1].strip('\t')
        sout = run_command(['ls -Sl %s' % dest], shell=True)
        md5out = run_command(['md5sum', dest])
        if not size in sout:
           raise Exception ('File did not download completely. '
                            'It should be %s and we got %s' % (size, sout))
        elif not checksum in  md5out:
           raise Exception ('The downloaded file is corrupted. '
                            'The checksum should %s and we got %s' %
                            (checksum, md5out))


    def download(self, device=None, channel=None, version=None, branch=None):
        """Download a zip file containing the test image. The user is
           expected to provide a clean input. A blank input means that
           we use defaults. Defaults will be the last build
           that the script attempted to download.

        @param device : The device under test. eg: x86-mario, link. This should
                        be the exact name of the device as shown in the
                        http://chromeos-images.
        @param channel: The channel under which we can get the test build.
                        eg: dev, beta, stable.
        @param version: The version of the build. eg:3701.0.0, 3701.71.0.
        @param branch : The branch under which we can find the version.
                        eg: R26, R27.

        @return final_dest: The complete downloaded file path.
        """
        # TODO: download stops at 4109631488, check why
        build_info = self.build_source(device=device, channel=channel,
                                       version=version, branch=branch)
        source = build_info[0]
        dest = '/tmp/%s/test' % build_info[1]
        final_dest = os.path.join(dest, os.path.basename(source))
        self.file_check(dest, folder=True, action=True)
        self.file_check(final_dest, folder=False, action=True)
        print 'Downloading %s, Please wait ...' % source
        run_command(['gsutil', 'cp', source, dest])
        self.file_check(final_dest, folder=False)
        self.check_download(final_dest, source)
        run_command(['nautilus', dest])
        return final_dest


    def build_source(self, device=None, channel=None,
                     version=None, branch=None):
        """Multiple option parser. Allows user to give arguments or options
           or call the function from their module to create the source path
           of the CrOS test build zip file to be downloaded. The user is
           expected to provide a clean input. A blank input means that we
           use defaults. Defaults will be the last build
           that the script attempted to download.

        @param device : The device under test. eg: x86-mario, link. This should
                        be the exact name of the device as shown in the
                        http://chromeos-images.
        @param channel: The channel under which we can get the test build.
                        eg: dev, beta, stable.
        @param version: The version of the build. eg:3701.0.0, 3701.71.0.
        @param branch : The branch under which we can find the version.
                        eg: R26, R27.
        """
        default = defaults()
        # We save the previous configuration as default
        prev_values = default.previous_defaults()
        defa_channel = prev_values['channel']
        defa_version = prev_values['version']
        defa_branch = prev_values['branch']
        defa_device = prev_values['device']
        if not (channel and branch and version and device):
            channel = raw_input('Enter the channel(default: %s): ' %
                                 defa_channel)
            device = raw_input('Enter the device(default: %s): ' %
                                defa_device)
            branch = raw_input('Enter the branch(default: %s): ' %
                                defa_branch)
            version = raw_input('Enter the version(default: %s): ' %
                                 defa_version)

        # Check the inputs again
        if not (channel and branch and version and device):
            if not (defa_channel and defa_branch and defa_version and
                    defa_device):
                raise Exception ('Insufficient input to download the build. '
                                 'Please use \"build_down.py --help\" to get '
                                 'more information about passing arguments.')
                sys.exit(0)
            if not channel:  # If no input, we use defaults
               channel = defa_channel
            if not branch:
               branch = defa_branch
            if not version:
               version = defa_version
            if not device:
               device = defa_device
        path = (self.image_path % (channel, device, version, branch,
                version, device))
        default.set_defaults(channel=channel, device=device,
                             version=version, branch=branch)
        return [path, device]


class unzip_burn():

   def unzip_file(self, zip_file):
       """ Unzip the given file into a folder with the same name.

       @param zip_file: The file to be unzipped.

       @return dest: The folder with unzipped files.
       """
       dest = os.path.splitext(zip_file)[0]
       # We avoid all the unnecesssary files to reduce the unzip time
       command = ['unzip', zip_file, '-d', dest, '-x',
                  'autotest.tar.bz2', 'chromiumos_base_image.bin',
                  'recovery_image.bin']
       large_zips = ['stout', 'link']
       for board in large_zips:
           if board in zip_file:
               command.append('chromiumos_qemu_image.bin')
               break
       if run_command(command):
           return dest


   def burn(self, image, drive):
       """ Burn the image to the given drive.

       @param image: The complete path to the image.
       @param drive: The complete path to the drive.
       """
       print 'Burning the image %s on to drive %s ...' % (image, drive)
       if run_command(['sudo dd if=%s of=%s' % (image, drive)],
                         shell=True):
          print 'Image is now on %s drive.'


def main():
    download = download_image()
    image = download.download()
    burn = unzip_burn()
    print 'Unzipping the folder, please wait ...'
    dest = burn.unzip_file(image)
    if dest:
       download_path = os.path.join(dest, 'chromiumos_test_image.bin')
       print 'The test image is in %s' % download_path
       drive_path = raw_input('Which drive to use?(default: /dev/sdc): ')
       if '/dev' not in drive_path:
          print 'Using the default drive path /dev/sdc.'
          drive_path = '/dev/sdc'
       if os.path.exists(download_path) and os.path.exists(drive_path):
           burn.burn(download_path, drive_path)


if __name__ == '__main__':
    main()
