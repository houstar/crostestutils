# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A convinient wrapper of the GCE python API.

Public methods in class GceContext raise HttpError when the underlining call to
Google API fails, or gce.Error on other failures.
"""

from __future__ import print_function

import httplib2

from chromite.lib import cros_logging as logging
from chromite.lib import timeout_util
from googleapiclient.discovery import build
from googleapiclient.http import HttpRequest
from googleapiclient import errors
from oauth2client.client import GoogleCredentials


class Error(Exception):
  """Base exception for this module."""


class CredentialsError(Error):
  """Exceptions raised when failed to construct credentials."""


class GceGoogleApiError(Error):
  """Wraps exceptions raised by googleapiclient.

  We wrap underlining exceptions in order to make the implementation detail
  transparent to users of this library, i.e., in most cases, they just need to
  catch 'gce.Error' and don't have to import googleapiclient.errors.
  """
  def __init__(self, error):
    super(GceGoogleApiError, self).__init__()
    if error is None or not isinstance(error, errors.Error):
      raise ValueError('error must be an instance of '
                       'googleapiclient.errors.Error; got %r' % error)
    self.error = error

  def __str__(self):
    return 'GCE API failure. %s: %s' % (type(self.error), str(self.error))


class GceContext(object):
  """A convinient wrapper around the GCE Python API."""

  GCE_SCOPES = [
      'https://www.googleapis.com/auth/compute',  # CreateInstance, CreateImage
      'https://www.googleapis.com/auth/devstorage.full_control', # CreateImage
      'https://www.googleapis.com/auth/devstorage.read_write', # CreateImage
      ]
  DEFAULT_MACHINE_TYPE = 'n1-standard-8'
  DEFAULT_TIMEOUT_SEC = 5 * 60

  def __init__(self, project, zone, network, machine_type, credentials,
               thread_safe=False):
    """Initializes GceContext.

    Args:
      project: The GCP project to create instances in.
      zone: The default zone to create instances in.
      network: The default network to create instances in.
      machine_type: The default machine type to use.
      credentials: The credentials used to call the GCE API.
      thread_safe: Whether the client is expected to be thread safe.
    """
    self.project = project
    self.zone = zone
    self.network = network
    self.machine_type = machine_type

    def BuildRequest(_, *args, **kwargs):
      """Create a new Http() object for every request."""
      http = httplib2.Http()
      http = credentials.authorize(http)
      return HttpRequest(http, *args, **kwargs)

    if thread_safe:
      self.gce_client = build('compute', 'v1', credentials=credentials,
                              requestBuilder=BuildRequest)
    else:
      self.gce_client = build('compute', 'v1', credentials=credentials)

  @classmethod
  def ForServiceAccount(cls, project, zone, network, machine_type,
                        json_key_file):
    """Creates a GceContext using service account credentials.

    About service account:
    https://developers.google.com/api-client-library/python/auth/service-accounts

    Args:
      project: The GCP project to create images and instances in.
      zone: The default zone to create instances in.
      network: The default network to create instances in.
      machine_type: The default machine type to use.
      json_key_file: Path to the service account JSON key.

    Returns:
      GceContext.
    """
    credentials = GoogleCredentials.from_stream(json_key_file).create_scoped(
        cls.GCE_SCOPES)
    return GceContext(project, zone, network, machine_type, credentials)

  @classmethod
  def ForServiceAccountThreadSafe(cls, project, zone, network, machine_type,
                                  json_key_file):
    """Creates a thread-safe GceContext using service account credentials.

    About service account:
    https://developers.google.com/api-client-library/python/auth/service-accounts

    Args:
      project: The GCP project to create images and instances in.
      zone: The default zone to create instances in.
      network: The default network to create instances in.
      machine_type: The default machine type to use.
      json_key_file: Path to the service account JSON key.

    Returns:
      GceContext.
    """
    credentials = GoogleCredentials.from_stream(json_key_file).create_scoped(
        cls.GCE_SCOPES)
    return GceContext(project, zone, network, machine_type, credentials,
                      thread_safe=True)

  def CreateInstance(self, name, image, machine_type=None, network=None,
                     zone=None, **kwargs):
    """Creates an instance with the given image and waits until it's ready.

    Args:
      name: Instance name.
      image:
        Fully spelled URL of the image, e.g., for private images,
        'global/images/my-private-image', or for images from a
        publicly-available project,
        'projects/debian-cloud/global/images/debian-7-wheezy-vYYYYMMDD'.
        Details:
        https://cloud.google.com/compute/docs/reference/latest/instances/insert
      machine_type: The machine type to use.
      network: An existing network to create the instance in.
      zone:
        The zone to create the instance in. Default zone will be used if
        omitted.
      kwargs:
        Other possible Instance Resource properties.
        https://cloud.google.com/compute/docs/reference/latest/instances#resource

    Returns:
      URL to the created instance.
    """
    machine_type = 'zones/%s/machineTypes/%s' % (
        zone or self.zone, machine_type or self.machine_type)
    # Allow machineType overriding.
    if 'machineType' in kwargs.keys():
      machine_type = kwargs['machineType']

    config = {
        'name': name,
        'machineType': machine_type,
        'disks': [
            {
                'boot': True,
                'autoDelete': True,
                'initializeParams': {
                    'sourceImage': image
                    }
                }
            ],
        'networkInterfaces': [
            {
                'network': 'global/networks/%s' % (network or self.network),
                'accessConfigs': [
                    {'type': 'ONE_TO_ONE_NAT', 'name': 'External NAT'}
                    ]
                }
            ]
        }
    config.update(**kwargs)
    operation = self.gce_client.instances().insert(
        project=self.project,
        zone=zone or self.zone,
        body=config).execute()
    self._WaitForZoneOperation(operation['name'], timeout_handler=lambda:
                               self.DeleteInstance(name))
    return operation['targetLink']

  def DeleteInstance(self, name, zone=None):
    """Deletes an instance with the name and waits until it's done.

    Args:
      name: Name of the instance to delete.
      zone: Zone where the instance is in. Default zone will be used if omitted.
    """
    operation = self.gce_client.instances().delete(
        project=self.project,
        zone=zone or self.zone,
        instance=name).execute()
    self._WaitForZoneOperation(operation['name'])

  def CreateImage(self, name, source):
    """Creates an image with the given |source|.

    Args:
      name: Name of the image to be created.
      source:
        Google Cloud Storage object of the source disk, e.g.,
        'https://storage.googleapis.com/my-gcs-bucket/test_image.tar.gz'.

    Returns:
      URL to the created image.
    """
    config = {
        'name': name,
        'rawDisk': {
            'source': source
            }
        }
    operation = self.gce_client.images().insert(
        project=self.project,
        body=config).execute()
    self._WaitForGlobalOperation(operation['name'], timeout_handler=lambda:
                                 self.DeleteImage(name))
    return operation['targetLink']

  def DeleteImage(self, name):
    """Deletes an image and waits until it's deleted.

    Args:
      name: Name of the image to delete.
    """
    operation = self.gce_client.images().delete(
        project=self.project,
        image=name).execute()
    self._WaitForGlobalOperation(operation['name'])

  def ListInstances(self, zone=None):
    """Lists all instances.

    Args:
      zone: Zone where the instances are in. Default zone will be used if
            omitted.
    """
    result = self.gce_client.instances().list(project=self.project,
                                              zone=zone or self.zone).execute()
    try:
      return result['items']
    except KeyError:
      return []

  def ListImages(self):
    """Lists all images."""
    result = self.gce_client.images().list(project=self.project).execute()

    try:
      return result['items']
    except KeyError:
      return []

  def GetInstance(self, instance, zone=None):
    """Gets an Instance Resource by name and zone.

    Args:
      instance: Name of the instance.
      zone: Zone where the instance is in. Default zone will be used if omitted.

    Returns:
      An Instance Resource.
    """
    result = self.gce_client.instances().get(project=self.project,
                                             zone=zone or self.zone,
                                             instance=instance).execute()
    return result

  def GetInstanceIP(self, instance, zone=None):
    """Gets the external IP of an instance.

    Args:
      instance: Name of the instance to get IP for.
      zone: Zone where the instance is in. Default zone will be used if omitted.

    Returns:
      External IP address of the instance.

    Raises:
      gce.Error on failures.
    """
    result = self.GetInstance(instance, zone)
    if not result:
      raise Error('Instance %s does not exist in zone %s.'
                  % (instance, zone or self.zone))
    try:
      return result['networkInterfaces'][0]['accessConfigs'][0]['natIP']
    except (KeyError, IndexError):
      raise Error('Failed to get IP address for instance %s' % instance)

  def GetImage(self, image):
    """Gets an Image Resource by name.

    Args:
      image: Name of the image to look for.

    Returns:
      An Image Resource.
    """
    result = self.gce_client.images().get(project=self.project,
                                          image=image).execute()
    return result

  def InstanceExists(self, instance, zone=None):
    """Checks if an instance exists in the current project.

    Args:
      instance: Name of the instance to check existence of.  zone: Zone where
      the instance is in. Default zone will be used if omitted.

    Returns:
      True if the instance exists or False otherwise.
    """
    result = self.GetInstance(instance, zone)
    return (result is not None)

  def ImageExists(self, image):
    """Checks if an image exists in the current project.

    Args:
      instance: Name of the image to check existence of.

    Returns:
      True if the instance exists or False otherwise.
    """
    result = self.GetImage(image)
    return (result is not None)

  def _WaitForZoneOperation(self, operation, zone=None, timeout_handler=None):
    get_request = self.gce_client.zoneOperations().get(
        project=self.project, zone=zone or self.zone, operation=operation)
    self._WaitForOperation(operation, get_request,
                           timeout_handler=timeout_handler)

  def _WaitForGlobalOperation(self, operation, timeout_handler=None):
    get_request = self.gce_client.globalOperations().get(project=self.project,
                                                         operation=operation)
    self._WaitForOperation(operation, get_request,
                           timeout_handler=timeout_handler)

  def _WaitForOperation(self, operation, get_operation_request,
                        timeout_handler=None):
    """Waits until timeout or the request gets a response with a 'DONE' status.

    Args:
      operation: The GCE operation to wait for.
      get_operation_request:
        The HTTP request to get the operation's status.
        This request will be executed periodically until it returns a status
        'DONE'.
      timeout_handler: A callable to be executed when times out.
    """
    def _IsDone():
      result = get_operation_request.execute()
      if result['status'] == 'DONE':
        if 'error' in result:
          raise Error(result['error'])
        return True
      return False

    try:
      logging.info('Waiting for operation [%s] to complete...' % operation)
      timeout = self.DEFAULT_TIMEOUT_SEC
      timeout_util.WaitForReturnTrue(_IsDone, timeout, period=1)
    except timeout_util.TimeoutError:
      if not timeout_handler:
        timeout_handler()
      raise Error('Timeout wating for operation [%s] to complete' % operation)
