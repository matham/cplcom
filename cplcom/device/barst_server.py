
from pybarst.core.server import BarstServer

from kivy.properties import ConfigParserProperty

from moa.compat import unicode_type, bytes_type
from moa.base import MoaBase
from moa.threads import ScheduledEventLoop

from cplcom import device_config_name
from cplcom.device import DeviceStageInterface


class Server(MoaBase, ScheduledEventLoop, DeviceStageInterface):
    '''Server device which creates and opens the Barst server.
    '''

    def create_device(self):
        # create actual server
        self.target = BarstServer(
            barst_path=(self.server_path if self.server_path else None),
            pipe_name=self.server_pipe)

    def start_channel(self):
        server = self.target
        server.open_server()

    def stop_channel(self, *largs, **kwargs):
        self.target.close_server()

    server_path = ConfigParserProperty(
        '', 'Server', 'barst_path', device_config_name, val_type=unicode_type)
    '''The full path to the Barst executable. Could be empty if the server
    is already started, on remote computer, or if it's in the typical
    `Program Files` path. If the server is not running, this path is needed
    to launch the server.

    Defaults to `''`.
    '''

    server_pipe = ConfigParserProperty(b'', 'Server', 'pipe',
                                       device_config_name, val_type=bytes_type)
    '''The full path to the pipe name (to be) used by the server. Examples are
    ``\\\\remote_name\pipe\pipe_name``, where ``remote_name`` is the name of
    the remote computer, or a period (`.`) if the server is local, and
    ``pipe_name`` is the name of the pipe used to create the server.

    Defaults to `''`.
    '''
