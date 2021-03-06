# The MIT License (MIT)
#
# Copyright (c) 2016 WUSTL ZPLAB
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Authors: Erik Hvatum <ice.rikh@gmail.com>

from PyQt5 import Qt
import sdl2
from ..client_util import joypad_input

class _SDLEventLoopThread(Qt.QThread):
    def __init__(self, joypad_input, parent=None):
        super().__init__(parent)
        self.joypad_input = joypad_input

    def run(self):
        self.joypad_input.event_loop()

class _JoypadInput(joypad_input.JoypadInput):
    def __init__(
            self,
            joypad_input_widget,
            input_device_index=0,
            input_device_name=None,
            scope_server_host='127.0.0.1',
            zmq_context=None,
            maximum_portion_of_wallclock_time_allowed_for_axis_commands=joypad_input.JoypadInput.DEFAULT_MAX_AXIS_COMMAND_WALLCLOCK_TIME_PORTION,
            maximum_axis_command_cool_off=joypad_input.JoypadInput.DEFAULT_MAX_AXIS_COMMAND_COOL_OFF):
        super().__init__(
            input_device_index=input_device_index,
            input_device_name=input_device_name,
            scope_server_host=scope_server_host,
            zmq_context=zmq_context,
            maximum_portion_of_wallclock_time_allowed_for_axis_commands=maximum_portion_of_wallclock_time_allowed_for_axis_commands,
            maximum_axis_command_cool_off=maximum_axis_command_cool_off)
        self.joypad_input_widget = joypad_input_widget
        self.handle_button_callback = self._handle_button_callback

    @staticmethod
    def _handle_button_callback(self, button_idx, pressed):
        self.joypad_input_widget.button_signal.emit(button_idx, pressed)

    def handle_joyhatmotion(self, hat_idx, pos):
        self.joypad_input_widget.hat_signal.emit(hat_idx, pos)

    def make_and_start_event_loop_thread(self):
        assert not self.event_loop_is_running
        self.thread = _SDLEventLoopThread(self)
        self.thread.start()

    def stop_and_destroy_event_loop_thread(self):
        assert self.event_loop_is_running
        self.exit_event_loop()
        self.thread.wait()
        del self.thread

    def handle_device_removed(self):
        self.joypad_input_widget.connected_input_removed_signal.emit()

# JoypadInputWidget is actually just a QAction.  QAction provides all the functionality required while avoiding
# the need to make and lay out a QPushButton.
class JoypadInputWidget(Qt.QAction):
    button_signal = Qt.pyqtSignal(int, bool)
    hat_signal = Qt.pyqtSignal(int, int)
    connected_input_removed_signal = Qt.pyqtSignal()

    @staticmethod
    def can_run(scope):
        return hasattr(scope, 'stage')

    def __init__(self, host, scope, scope_properties, device_id=-1, parent=None):
        """If -1 (the default) is supplied for device_id, JoypadInputWidget attempts to use the gamepad/joystick with
        the lowest ID if on one is available, displays a device selection dialog if multiple are available, and remains
        in the disconnected state if none are available.  Supplying None (the default) for device_id results in the
        gamepad/joystick with the lowest ID being used if only one device is available, an error messagebox being
        displayed if there are no devices available, and a device selection dialog being displayed if multiple devices
        are available.  Supplying any other value connects to the specified gamepad/joystick and displays an error
        messagebox if this fails.

        If connect is called while already connected, the existing connection is closed, and a new connection is
        made following the rules described above."""
        super().__init__(parent)
        self.scope = scope
        self.scope_properties = scope_properties
        self.scope_server_host = host
        self.joypad_input = None
        self.setText('Connect Joypad')
        Qt.QApplication.instance().aboutToQuit.connect(self.disconnect)
        self.button_signal.connect(self.on_button_signal)
        self.connected_input_removed_signal.connect(self.on_connected_input_removed_signal)
        self.triggered.connect(self.on_triggered)
        self.connect(device_id)

    def on_button_signal(self, button_idx, pressed):
        if button_idx == sdl2.SDL_CONTROLLER_BUTTON_A:
            # Stop all stage movement when what is typically the gamepad X button is pressed or released
            self.scope.stage.stop_x()
            self.scope.stage.stop_y()
            self.scope.stage.stop_z()

    def on_connected_input_removed_signal(self):
        self.disconnect()

    @property
    def is_connected(self):
        return self.joypad_input is not None

    def on_triggered(self):
        if self.is_connected:
            self.disconnect()
        else:
            self.connect(device_id=None)

    def connect(self, device_id=-1):
        self.disconnect()
        device_rows = sorted(joypad_input.enumerate_devices(), key=lambda v: v[0])
        if device_id in (-1, None):
            if not device_rows:
                if device_id is None:
                    m = "No gamepads/joysticks are available. Note that newly plugged-in gamepads/joysticks do not become " \
                        "available until Python is restarted."
                    Qt.QMessageBox.warning(None, "Joypad Error", m)
                return
            if len(device_rows) == 1:
                self.joypad_input = _JoypadInput(self, device_rows[0][0], scope_server_host=self.scope_server_host)
                device_name = device_rows[0][2]
            else:
                dlg = _JoypadDeviceSelectionDialog(device_rows)
                if dlg.exec() == Qt.QDialog.Accepted and dlg.selected_device_row is not None:
                    self.joypad_input = _JoypadInput(self, dlg.selected_device_row[0], scope_server_host=self.scope_server_host)
                    device_name = dlg.selected_device_row[2]
                else:
                    return
        else:
            for r in device_rows:
                if r[0] == device_id:
                    device_name = r[2]
                    self.joypad_input = _JoypadInput(self, device_id, scope_server_host=self.scope_server_host)
                    break
            else:
                raise ValueError('No SDL2 gamepad/joystick has ID {}.'.format(device_id))
        self.joypad_input.make_and_start_event_loop_thread()
        self.setText('Disconnect Joypad')
        self.setToolTip('Currently connected to "{}".'.format(device_name))

    def disconnect(self):
        if not self.is_connected:
            return
        self.joypad_input.stop_and_destroy_event_loop_thread()
        self.joypad_input = None
        self.setText('Connect Joypad')
        self.setToolTip(None)

class _JoypadDeviceSelectionDialog(Qt.QDialog):
    def __init__(self, device_rows, parent=None):
        super().__init__(parent)
        self.device_rows = device_rows
        self.setModal(True)
        self.setWindowModality(Qt.Qt.WindowModal)
        self.setWindowTitle('Select Gamepad/Joystick')
        self.setSizeGripEnabled(True)
        self.resize(865, 400)
        self.button_box = Qt.QDialogButtonBox(Qt.QDialogButtonBox.Ok | Qt.QDialogButtonBox.Cancel, Qt.Qt.Horizontal)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.connect_button = self.button_box.button(Qt.QDialogButtonBox.Ok)
        self.connect_button.setText('Connect')
        l = Qt.QVBoxLayout()
        self.setLayout(l)
        self.table_widget = Qt.QTableWidget()
        self.table_widget.setEditTriggers(Qt.QAbstractItemView.NoEditTriggers)
        self.table_widget.setSelectionMode(Qt.QAbstractItemView.SingleSelection)
        self.table_widget.setSelectionBehavior(Qt.QAbstractItemView.SelectRows)
        self.table_widget.setDragDropMode(Qt.QAbstractItemView.NoDragDrop)
        self.table_widget.setColumnCount(3)
        f = Qt.QFont()
        f.setFamily('Monospace')
        twi = Qt.QTableWidgetItem('ID')
        twi.setFont(f)
        self.table_widget.setHorizontalHeaderItem(0, twi)
        self.table_widget.setHorizontalHeaderItem(1, Qt.QTableWidgetItem('Type'))
        self.table_widget.setHorizontalHeaderItem(2, Qt.QTableWidgetItem('Name'))
        l.addWidget(self.table_widget)
        l.addWidget(self.button_box)
        sm = self.table_widget.selectionModel()
        sm.currentRowChanged.connect(self.on_table_widget_current_row_changed)
        self.selected_device_row = None
        self.table_widget.setRowCount(len(self.device_rows))
        sm.clear()
        for r_idx, r in enumerate(self.device_rows):
            self.table_widget.setItem(r_idx, 0, Qt.QTableWidgetItem(str(r[0])))
            self.table_widget.setItem(r_idx, 1, Qt.QTableWidgetItem(r[1]))
            self.table_widget.setItem(r_idx, 2, Qt.QTableWidgetItem(r[2]))
        if self.device_rows:
            self.table_widget.resizeColumnsToContents()
            sm.select(sm.model().index(0,0), sm.Rows | sm.Current | sm.Select)


    def on_table_widget_current_row_changed(self, midx, old_midx):
        if midx.isValid():
            self.connect_button.setEnabled(True)
            self.selected_device_row = self.device_rows[midx.row()]
        else:
            self.connect_button.setEnabled(False)
            self.selected_device_row = None