# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing classes pertaining to inserting a proxy in a test."""

import os
import select
import socket
import SocketServer
import threading


class Filter(object):
  """Base class for data filters.

     Pass subclass of this to CrosTestProxy which will perform whatever
     connection manipulation you prefer.
  """

  def setup(self):
    """This setup method is called once per connection."""
    pass

  def InBound(self, data):
    """This method is called once per packet of incoming data.

       The value returned is what is sent through the proxy. If
       None is returned, the connection will be closed.
    """
    return data

  def OutBound(self, data):
    """This method is called once per packet of outgoing data.

       The value returned is what is sent through the proxy. If
       None is returned, the connection will be closed.
    """
    return data


class CrosTestProxy(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
  """A transparent proxy for simulating network errors"""

  class _Handler(SocketServer.BaseRequestHandler):
    """Proxy connection handler that passes data though a filter"""

    def setup(self):
      """Setup is called once for each connection proxied."""
      self.server.filter.setup()

    def handle(self):
      """Handles each incoming connection.

         Opens a new connection to the port we are proxing to, then
         passes each packet along in both directions after passing
         them through the filter object passed in.
      """
      # Open outgoing socket
      s_in = self.request
      s_out = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      s_out.connect((self.server.address_out, self.server.port_out))

      while True:
        rlist, wlist, xlist = select.select([s_in, s_out], [], [])

        if s_in in rlist:
          data = s_in.recv(1024)
          data = self.server.filter.InBound(data)
          if not data: break
          try:
            # If there is any error sending data, close both connections.
            s_out.sendall(data)
          except socket.error:
            break

        if s_out in rlist:
          data = s_out.recv(1024)
          data = self.server.filter.OutBound(data)
          if not data: break
          try:
            # If there is any error sending data, close both connections.
            s_in.sendall(data)
          except socket.error:
            break

      s_in.close()
      s_out.close()

  def __init__(self,
               filter,
               port_in=8081,
               address_out='127.0.0.1', port_out=8080):
    """Configures the proxy object.

    Args:
      filter: An instance of a subclass of Filter.
      port_in: Port on which to listen for incoming connections.
      address_out: Address to which outgoing connections will go.
      address_port: Port to which outgoing connections will go.
    """
    self.port_in = port_in
    self.address_out = address_out
    self.port_out = port_out
    self.filter = filter

    # Used to coordinate startup/shutdown in a new thread.
    self.__is_started = threading.Event()
    self.__is_shut_down = threading.Event()
    self.__serving = False

    try:
      SocketServer.TCPServer.__init__(self,
                                      ('', port_in),
                                      self._Handler)
    except socket.error:
      os.system('sudo netstat -l --tcp -n -p')
      raise

  def serve_forever_in_thread(self):
    """Helper method to start the server in a new background thread."""
    server_thread = threading.Thread(target=self.serve_forever)
    server_thread.setDaemon(True)
    server_thread.start()

    # Wait until the server is started, bug chromium-os:16574
    self.__is_started.wait()

    return server_thread

  # ==========================

  # Override of the version of this method from SocketServer.
  # It's duplicated, other than adding __is_started event.
  # Bug chromium-os:16574
  def serve_forever(self, poll_interval=0.5):
    """Handle one request at a time until shutdown.

    Polls for shutdown every poll_interval seconds. Ignores
    self.timeout. If you need to do periodic tasks, do them in
    another thread.
    """
    self.__serving = True
    self.__is_shut_down.clear()
    self.__is_started.set()

    while self.__serving:
      # XXX: Consider using another file descriptor or
      # connecting to the socket to wake this up instead of
      # polling. Polling reduces our responsiveness to a
      # shutdown request and wastes cpu at all other times.
      r, w, e = select.select([self], [], [], poll_interval)
      if r:
        self._handle_request_noblock()

    self.__is_started.clear()
    self.__is_shut_down.set()

  # Duplicate override of the version of this method from SocketServer so
  # that we can access the same __ variables as serve_forever.
  # Bug chromium-os:16574
  def shutdown(self):
    """Stops the serve_forever loop.

    Blocks until the loop has finished. This must be called while
    serve_forever() is running in another thread, or it will
    deadlock.
    """
    self.__serving = False
    self.__is_shut_down.wait()

