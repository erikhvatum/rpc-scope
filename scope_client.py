import functools
import zmq
import time
import collections
import numpy

from .simple_rpc import rpc_client, property_client
from . import scope_configuration as config
from . import ism_buffer_utils

def wrap_image_getter(namespace, func_name, get_data):
    function = getattr(namespace, func_name)
    @functools.wraps(function)
    def wrapped():
        return get_data(function())
    setattr(namespace, func_name, wrapped)

def wrap_images_getter(namespace, func_name, get_data):
    function = getattr(namespace, func_name)
    @functools.wraps(function)
    def wrapped():
        return [get_data(name) for name in function()]
    setattr(namespace, func_name, wrapped)

def rpc_client_main(rpc_port=None, rpc_interrupt_port=None, context=None):
    if rpc_port is None:
        rpc_port = config.Server.RPC_PORT
    if rpc_interrupt_port is None:
        rpc_interrupt_port = config.Server.RPC_INTERRUPT_PORT

    client = rpc_client.ZMQClient(rpc_port, rpc_interrupt_port, context)
    scope = client.proxy_namespace()
    is_local, get_data = ism_buffer_utils.client_get_data_getter(client)
    scope._get_data = get_data
    scope._is_local = is_local
    if not is_local:
        scope.camera.set_network_compression = get_data.set_network_compression
    scope._rpc_client = client
    if hasattr(scope, 'camera'):
        wrap_image_getter(scope.camera, 'acquire_image', get_data)
        wrap_image_getter(scope.camera, 'live_image', get_data)
        wrap_image_getter(scope.camera, 'next_image', get_data)
        if hasattr(scope.camera, 'acquisition_sequencer'):
            wrap_images_getter(scope.camera.acquisition_sequencer, 'run', get_data)
    return scope

def property_client_main(property_port=None, context=None):
    if property_port is None:
        property_port = config.Server.PROPERTY_PORT
    scope_properties = property_client.ZMQClient(property_port, context)
    return scope_properties


def client_main(rpc_port=None, rpc_interrupt_port=None, property_port=None, context=None, subscribe_all=True):
    if context is None:
        context = zmq.Context()
    scope = rpc_client_main(rpc_port, rpc_interrupt_port, context)
    scope_properties = property_client_main(property_port, context)
    if subscribe_all:
        # have the property client subscribe to all properties. Even with a no-op callback,
        # this causes the client to keep its internal 'properties' dictionary up-to-date
        scope_properties.subscribe_prefix('', lambda x, y: None)
        scope.rebroadcast_properties()
    return scope, scope_properties

class LiveStreamer:
    def __init__(self, scope, scope_properties, image_ready_callback):
        self.scope = scope
        self.image_ready_callback = image_ready_callback
        self.image_received = False
        self.live = False
        self.last_times = collections.deque(maxlen=10)
        self._last_time = time.time()
        scope_properties.subscribe('scope.camera.live_mode', self._live_change, valueonly=True)
        scope_properties.subscribe('scope.camera.live_frame', self._live_update, valueonly=True)

    def get_image(self):
        assert self.image_received
        # get image before re-enabling image-receiving because if this is over the network, it could take a while
        image = self.scope.camera.live_image()
        t = time.time()
        self.last_times.append(t - self._last_time)
        self._last_time = t
        self.image_received = False
        return image, self.frame_no

    def get_fps(self):
        if not self.live:
            return
        return 1/numpy.mean(self.last_times)

    def _live_change(self, live):
        # called in property_client's thread: note we can't do RPC calls
        self.live = live
        self.last_times.clear()
        self._last_time = time.time()

    def _live_update(self, frame_no):
        # called in property client's thread: note we can't do RPC calls
        # if we've already received an image, but nobody on the main thread
        # has called get_image() to retrieve it, then just ignore subsequent
        # updates
        if not self.image_received:
            self.image_received = True
            self.frame_no = frame_no
            self.image_ready_callback()
