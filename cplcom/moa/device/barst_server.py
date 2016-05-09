import time
import re

from pybarst.core.server import BarstServer

from moa.threads import ScheduledEventLoop
from moa.device import Device
from cplcom.moa.device import DeviceExceptionBehavior

from kivy.properties import BooleanProperty, StringProperty, ObjectProperty

__all__ = ('Server', )

_local_server_pat = re.compile(r'\\\\\.\\pipe.+')


class Server(DeviceExceptionBehavior, Device, ScheduledEventLoop):
    '''Server device which creates and opens the Barst server.
    '''

    __settings_attrs__ = ('server_path', 'server_pipe')

    def activate(self, *largs, **kwargs):
        kwargs['state'] = 'activating'
        if super(Server, self).activate(*largs, **kwargs):
            self.start_thread()
            self.server = BarstServer(
                barst_path=(self.server_path if self.server_path else None),
                pipe_name=self.server_pipe)

            def finish_activate(*largs):
                self.activation = 'active'
            self.request_callback(self._start_server, finish_activate)
            return True
        return False

    def _start_server(self):
        server = self.server
        if self.restart and re.match(_local_server_pat, self.server_pipe):
            try:
                server.close_server()
            except:
                pass
            # XXX: fix server to wait out
            time.sleep(1.)
        server.open_server()

    def deactivate(self, *largs, **kwargs):
        if not re.match(_local_server_pat, self.server_pipe):
            if super(Server, self).deactivate(*largs, **kwargs):
                self.stop_thread()
                return True
            return False

        kwargs['state'] = 'deactivating'
        if super(Server, self).deactivate(*largs, **kwargs):
            def finish_deactivate(*largs):
                self.activation = 'inactive'
                self.stop_thread()
            self.request_callback(
                self.server.close_server, finish_deactivate)
            return True
        return False

    server = ObjectProperty()
    '''The internal barst server.
    '''

    restart = BooleanProperty(True)
    '''If True (and the server is local) will restart the server if it's
    already open.
    '''

    server_path = StringProperty('')
    '''The full path to the Barst executable. Could be empty if the server
    is already started, on remote computer, or if it's in the typical
    `Program Files` path. If the server is not running, this path is needed
    to launch the server.

    Defaults to `''`.
    '''

    server_pipe = StringProperty('')
    '''The full path to the pipe name (to be) used by the server. Examples are
    ``\\\\remote_name\pipe\pipe_name``, where ``remote_name`` is the name of
    the remote computer, or a period (`.`) if the server is local, and
    ``pipe_name`` is the name of the pipe used to create the server.

    Defaults to `''`.
    '''
