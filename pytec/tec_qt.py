from PyQt6 import QtWidgets, QtGui, QtCore
from PyQt6.QtCore import pyqtSignal, QObject, QSignalBlocker, pyqtSlot
import pyqtgraph.parametertree.parameterTypes as pTypes
from pyqtgraph.parametertree import Parameter, ParameterTree, ParameterItem, registerParameterType
import pyqtgraph as pg
pg.setConfigOptions(antialias=True)
from pglive.sources.data_connector import DataConnector
from pglive.kwargs import Axis
from pglive.sources.live_plot import LiveLinePlot
from pglive.sources.live_plot_widget import LivePlotWidget
from pglive.sources.live_axis import LiveAxis
import sys
import argparse
import logging
import asyncio
from pytec.aioclient import Client, StoppedConnecting
import qasync
from qasync import asyncSlot, asyncClose
from autotune import PIDAutotune, PIDAutotuneState

# pyuic6 -x tec_qt.ui  -o ui_tec_qt.py
from ui_tec_qt import Ui_MainWindow

"""Number of channels provided by the Thermostat"""
NUM_CHANNELS: int = 2

def get_argparser():
    parser = argparse.ArgumentParser(description="ARTIQ master")

    parser.add_argument("--connect", default=None, action="store_true",
                        help="Automatically connect to the specified Thermostat in IP:port format")
    parser.add_argument('IP', metavar="ip", default=None, nargs='?')
    parser.add_argument('PORT', metavar="port", default=None, nargs='?')
    parser.add_argument("-l", "--log", dest="logLevel", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help="Set the logging level")

    return parser


class MutexParameter(pTypes.ListParameter):
    """
    Mutually exclusive parameter where only one of its children is visible at a time, list selectable.

    The ordering of the list items determines which children will be visible.
    """
    def __init__(self, **opts):
        super().__init__(**opts)

        self.sigValueChanged.connect(self.show_chosen_child)
        self.sigValueChanged.emit(self, self.opts['value'])

    def _get_param_from_value(self, value):
        if isinstance(self.opts['limits'], dict):
            values_list = list(self.opts['limits'].values())
        else:
            values_list = self.opts['limits']

        return self.children()[values_list.index(value)]

    @pyqtSlot(object, object)
    def show_chosen_child(self, value):
        for param in self.children():
            param.hide()

        child_to_show = self._get_param_from_value(value.value())
        child_to_show.show()

        if child_to_show.opts.get('triggerOnShow', None):
            child_to_show.sigValueChanged.emit(child_to_show, child_to_show.value())


registerParameterType('mutex', MutexParameter)


class WrappedClient(QObject, Client):
    connection_error = pyqtSignal()

    async def _read_line(self):
        try:
            return await super()._read_line()
        except (OSError, TimeoutError, asyncio.TimeoutError) as e: # TODO: Remove asyncio.TimeoutError in Python 3.11
            logging.error("Client connection error, disconnecting", exc_info=True)
            self.connection_error.emit()


class ClientWatcher(QObject):
    fan_update = pyqtSignal(dict)
    pwm_update = pyqtSignal(list)
    report_update = pyqtSignal(list)
    pid_update = pyqtSignal(list)
    thermistor_update = pyqtSignal(list)
    postfilter_update = pyqtSignal(list)

    def __init__(self, parent, client, update_s):
        self._update_s = update_s
        self._client = client
        self._watch_task = None
        self._report_mode_task = None
        self._poll_for_report = True
        super().__init__(parent)

    async def run(self):
        loop = asyncio.get_running_loop()
        while True:
            time = loop.time()
            await self.update_params()
            await asyncio.sleep(self._update_s - (loop.time() - time))

    async def update_params(self):
        self.fan_update.emit(await self._client.get_fan())
        self.pwm_update.emit(await self._client.get_pwm())
        if self._poll_for_report:
            self.report_update.emit(await self._client.report())
        self.pid_update.emit(await self._client.get_pid())
        self.thermistor_update.emit(await self._client.get_steinhart_hart())
        self.postfilter_update.emit(await self._client.get_postfilter())

    def start_watching(self):
        self._watch_task = asyncio.create_task(self.run())

    @pyqtSlot()
    def stop_watching(self):
        if self._watch_task is not None:
            self._watch_task.cancel()
            self._watch_task = None

    async def set_report_mode(self, enabled: bool):
        self._poll_for_report = not enabled
        if enabled:
            self._report_mode_task = asyncio.create_task(self.report_mode())
        else:
            self._client.stop_report_mode()
            if self._report_mode_task is not None:
                await self._report_mode_task
                self._report_mode_task = None

    async def report_mode(self):
        async for report in self._client.report_mode():
            self.report_update.emit(report)

    @pyqtSlot(float)
    def set_update_s(self, update_s):
        self._update_s = update_s


class ChannelGraphs:
    """Manager of a channel's two graphs and their elements."""

    """The maximum number of sample points to store."""
    DEFAULT_MAX_SAMPLES = 1000

    def __init__(self, t_widget, i_widget):
        self._t_widget = t_widget
        self._i_widget = i_widget

        self._t_plot = LiveLinePlot()
        self._i_plot = LiveLinePlot(name="Measured")
        self._iset_plot = LiveLinePlot(name="Set", pen=pg.mkPen('r'))

        self._t_line = self._t_widget.getPlotItem().addLine(label='{value} °C')
        self._t_line.setVisible(False)
        self._t_setpoint_plot = LiveLinePlot() # Hack for keeping setpoint line in plot range

        for graph in t_widget, i_widget:
            time_axis = LiveAxis('bottom', text="Time since Thermostat reset", **{Axis.TICK_FORMAT: Axis.DURATION})
            time_axis.showLabel()
            graph.setAxisItems({'bottom': time_axis})

            graph.add_crosshair(pg.mkPen(color='red', width=1), {'color': 'green'})

            # Enable linking of axes in the graph widget's context menu
            graph.register(graph.getPlotItem().titleLabel.text) # Slight hack getting the title

        temperature_axis = LiveAxis('left', text="Temperature", units="°C")
        temperature_axis.showLabel()
        t_widget.setAxisItems({'left': temperature_axis})

        current_axis = LiveAxis('left', text="Current", units="A")
        current_axis.showLabel()
        i_widget.setAxisItems({'left': current_axis})
        i_widget.addLegend(brush=(50, 50, 200, 150))

        t_widget.addItem(self._t_plot)
        t_widget.addItem(self._t_setpoint_plot)
        i_widget.addItem(self._i_plot)
        i_widget.addItem(self._iset_plot)

        self.t_connector = DataConnector(self._t_plot, max_points=self.DEFAULT_MAX_SAMPLES)
        self.t_setpoint_connector = DataConnector(self._t_setpoint_plot, max_points=1)
        self.i_connector = DataConnector(self._i_plot, max_points=self.DEFAULT_MAX_SAMPLES)
        self.iset_connector = DataConnector(self._iset_plot, max_points=self.DEFAULT_MAX_SAMPLES)

        self.max_samples = self.DEFAULT_MAX_SAMPLES

    def plot_append(self, report):
        temperature = report['temperature']
        current = report['tec_i']
        iset = report['i_set']
        time = report['time']

        if temperature is not None:
            self.t_connector.cb_append_data_point(temperature, time)
            if self._t_line.isVisible():
                self.t_setpoint_connector.cb_append_data_point(self._t_line.value(), time)
            else:
                self.t_setpoint_connector.cb_append_data_point(temperature, time)
            if current is not None:
                self.i_connector.cb_append_data_point(current, time)
            self.iset_connector.cb_append_data_point(iset, time)

    def clear(self):
        for connector in self.t_connector, self.i_connector, self.iset_connector:
            connector.clear()

    def set_t_line(self, temp=None, visible=None):
        if visible is not None:
            self._t_line.setVisible(visible)
        if temp is not None:
            self._t_line.setValue(temp)

            # PyQtGraph normally does not update this text when the line
            # is not visible, so make sure that the temperature label 
            # gets updated always, and doesn't stay at an old value.
            self._t_line.label.setText(f"{temp} °C")


class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):

    """The maximum number of sample points to store."""
    DEFAULT_MAX_SAMPLES = 1000

    """Thermostat parameters that are particular to a channel"""
    THERMOSTAT_PARAMETERS = [[
        {'name': 'Temperature', 'type': 'float', 'format': '{value:.4f} °C', 'readonly': True},
        {'name': 'Current through TEC', 'type': 'float', 'suffix': 'mA', 'decimals': 6, 'readonly': True},
        {'name': 'Output Config', 'expanded': True, 'type': 'group', 'children': [
            {'name': 'Control Method', 'type': 'mutex', 'limits': ['Constant Current', 'Temperature PID'],
            'activaters': [None, ('pwm', ch, 'pid')], 'children': [
                {'name': 'Set Current', 'type': 'float', 'value': 0, 'step': 100, 'limits': (-3000, 3000), 'triggerOnShow': True,
                'decimals': 6, 'suffix': 'mA', 'param': ('pwm', ch, 'i_set')},
                {'name': 'Set Temperature', 'type': 'float', 'value': 25, 'step': 0.1, 'limits': (-273, 300),
                'format': '{value:.4f} °C', 'param': ('pid', ch, 'target')},
            ]},
            {'name': 'Limits', 'expanded': False, 'type': 'group', 'children': [
                {'name': 'Max Cooling Current', 'type': 'float', 'value': 0, 'step': 100, 'decimals': 6, 'limits': (0, 3000),
                'suffix': 'mA', 'param': ('pwm', ch, 'max_i_pos')},
                {'name': 'Max Heating Current', 'type': 'float', 'value': 0, 'step': 100, 'decimals': 6, 'limits': (0, 3000),
                'suffix': 'mA', 'param': ('pwm', ch, 'max_i_neg')},
                {'name': 'Max Voltage Difference', 'type': 'float', 'value': 0, 'step': 0.1, 'limits': (0, 5), 'siPrefix': True,
                'suffix': 'V', 'param': ('pwm', ch, 'max_v')},
            ]}
        ]},
        {'name': 'Thermistor Config', 'expanded': False, 'type': 'group', 'children': [
            {'name': 'T₀', 'type': 'float', 'value': 25, 'step': 0.1, 'limits': (-100, 100),
            'format': '{value:.4f} °C', 'param': ('s-h', ch, 't0')},
            {'name': 'R₀', 'type': 'float', 'value': 10000, 'step': 1, 'siPrefix': True, 'suffix': 'Ω',
            'param': ('s-h', ch, 'r0')},
            {'name': 'B', 'type': 'float', 'value': 3950, 'step': 1, 'suffix': 'K', 'decimals': 4, 'param': ('s-h', ch, 'b')},
            {'name': 'Postfilter Rate', 'type': 'list', 'value': 16.67, 'param': ('postfilter', ch, 'rate'),
            'limits': {'Off': None, '16.67 Hz': 16.67, '20 Hz': 20.0, '21.25 Hz': 21.25, '27 Hz': 27.0}},
        ]},
        {'name': 'PID Config', 'expanded': False, 'type': 'group', 'children': [
            {'name': 'Kp', 'type': 'float', 'step': 0.1, 'suffix': '', 'param': ('pid', ch, 'kp')},
            {'name': 'Ki', 'type': 'float', 'step': 0.1, 'suffix': 'Hz', 'param': ('pid', ch, 'ki')},
            {'name': 'Kd', 'type': 'float', 'step': 0.1, 'suffix': 's', 'param': ('pid', ch, 'kd')},
            {'name': "PID Output Clamping", 'expanded': True, 'type': 'group', 'children': [
                {'name': 'Minimum', 'type': 'float', 'step': 100, 'limits': (-3000, 3000), 'decimals': 6, 'suffix': 'mA', 'param': ('pid', ch, 'output_min')},
                {'name': 'Maximum', 'type': 'float', 'step': 100, 'limits': (-3000, 3000), 'decimals': 6, 'suffix': 'mA', 'param': ('pid', ch, 'output_max')},
            ]},
            {'name': 'PID Auto Tune', 'expanded': False, 'type': 'group', 'children': [
                {'name': 'Target Temperature', 'type': 'float', 'value': 20, 'step': 0.1, 'format': '{value:.4f} °C'},
                {'name': 'Test Current', 'type': 'float', 'value': 1000, 'decimals': 6, 'step': 100, 'limits': (-3000, 3000), 'suffix': 'mA'},
                {'name': 'Temperature Swing', 'type': 'float', 'value': 1.5, 'step': 0.1, 'prefix': '±', 'format': '{value:.4f} °C'},
                {'name': 'Run', 'type': 'action', 'tip': 'Run'},
            ]},
        ]},
        {'name': 'Save to flash', 'type': 'action', 'tip': 'Save config to thermostat, applies on reset'},
        {'name': 'Load from flash', 'type': 'action', 'tip': 'Load config from flash'}
    ] for ch in range(NUM_CHANNELS)]

    def __init__(self, args):
        super().__init__()

        self.setupUi(self)

        self.ch0_t_graph.setTitle("Channel 0 Temperature")
        self.ch0_i_graph.setTitle("Channel 0 Current")
        self.ch1_t_graph.setTitle("Channel 1 Temperature")
        self.ch1_i_graph.setTitle("Channel 1 Current")

        self.max_samples = self.DEFAULT_MAX_SAMPLES

        self._set_up_connection_menu()
        self._set_up_thermostat_menu()
        self._set_up_plot_menu()

        self.client = WrappedClient(self)
        self.client.connection_error.connect(self.bail)
        self.client_watcher = ClientWatcher(self, self.client, self.report_refresh_spin.value())
        self.client_watcher.fan_update.connect(self.fan_update)
        self.client_watcher.report_update.connect(self.update_report)
        self.client_watcher.pid_update.connect(self.update_pid)
        self.client_watcher.pwm_update.connect(self.update_pwm)
        self.client_watcher.thermistor_update.connect(self.update_thermistor)
        self.client_watcher.postfilter_update.connect(self.update_postfilter)
        self.report_apply_btn.clicked.connect(
            lambda: self.client_watcher.set_update_s(self.report_refresh_spin.value())
        )

        self.params = [
            Parameter.create(name=f"Thermostat Channel {ch} Parameters", type='group', value=ch, children=self.THERMOSTAT_PARAMETERS[ch])
            for ch in range(NUM_CHANNELS)
        ]
        self._set_param_tree()

        self.channel_graphs = [
            ChannelGraphs(getattr(self, f'ch{ch}_t_graph'), getattr(self, f'ch{ch}_i_graph'))
            for ch in range(NUM_CHANNELS)
        ]

        self.autotuners = [
            PIDAutotune(25)
            for _ in range(NUM_CHANNELS)
        ]

        self.loading_spinner.hide()

        self.hw_rev_data = None

        if args.connect:
            if args.IP:
                self.host_set_line.setText(args.IP)
            if args.PORT:
                self.port_set_spin.setValue(int(args.PORT))
            self.connect_btn.click()

    def _set_up_connection_menu(self):
        self.connection_menu = QtWidgets.QMenu()
        self.connection_menu.setTitle('Connection Settings')

        self.host_set_line = QtWidgets.QLineEdit()
        self.host_set_line.setMinimumSize(QtCore.QSize(160, 0))
        self.host_set_line.setMaximumSize(QtCore.QSize(160, 16777215))
        self.host_set_line.setMaxLength(15)
        self.host_set_line.setClearButtonEnabled(True)

        def connect_on_enter_press():
            self.connect_btn.click()
            self.connection_menu.hide()
        self.host_set_line.returnPressed.connect(connect_on_enter_press)

        self.host_set_line.setText("192.168.1.26")
        self.host_set_line.setPlaceholderText("IP for the Thermostat")

        host = QtWidgets.QWidgetAction(self.connection_menu)
        host.setDefaultWidget(self.host_set_line)
        self.connection_menu.addAction(host)
        self.connection_menu.host = host

        self.port_set_spin = QtWidgets.QSpinBox()
        self.port_set_spin.setMinimumSize(QtCore.QSize(70, 0))
        self.port_set_spin.setMaximumSize(QtCore.QSize(70, 16777215))
        self.port_set_spin.setMaximum(65535)
        self.port_set_spin.setValue(23)

        def connect_only_if_enter_pressed():
            if not self.port_set_spin.hasFocus(): # Don't connect if the spinbox only lost focus
                return;
            connect_on_enter_press()
        self.port_set_spin.editingFinished.connect(connect_only_if_enter_pressed)

        port = QtWidgets.QWidgetAction(self.connection_menu)
        port.setDefaultWidget(self.port_set_spin)
        self.connection_menu.addAction(port)
        self.connection_menu.port = port

        self.exit_button = QtWidgets.QPushButton()
        self.exit_button.setText("Exit GUI")
        self.exit_button.pressed.connect(QtWidgets.QApplication.instance().quit)

        exit_action = QtWidgets.QWidgetAction(self.exit_button)
        exit_action.setDefaultWidget(self.exit_button)
        self.connection_menu.addAction(exit_action)
        self.connection_menu.exit_action = exit_action

        self.connect_btn.setMenu(self.connection_menu)

    def _set_up_thermostat_menu(self):
        self.thermostat_menu = QtWidgets.QMenu()
        self.thermostat_menu.setTitle('Thermostat settings')

        self.fan_group = QtWidgets.QWidget()
        self.fan_group.setEnabled(False)
        self.fan_group.setMinimumSize(QtCore.QSize(40, 0))
        self.fan_layout = QtWidgets.QHBoxLayout(self.fan_group)
        self.fan_layout.setSpacing(9)
        self.fan_lbl = QtWidgets.QLabel(parent=self.fan_group)
        self.fan_lbl.setMinimumSize(QtCore.QSize(40, 0))
        self.fan_lbl.setMaximumSize(QtCore.QSize(40, 16777215))
        self.fan_lbl.setBaseSize(QtCore.QSize(40, 0))
        self.fan_layout.addWidget(self.fan_lbl)
        self.fan_power_slider = QtWidgets.QSlider(parent=self.fan_group)
        self.fan_power_slider.setMinimumSize(QtCore.QSize(200, 0))
        self.fan_power_slider.setMaximumSize(QtCore.QSize(200, 16777215))
        self.fan_power_slider.setBaseSize(QtCore.QSize(200, 0))
        self.fan_power_slider.setRange(1, 100)
        self.fan_power_slider.setOrientation(QtCore.Qt.Orientation.Horizontal)
        self.fan_layout.addWidget(self.fan_power_slider)
        self.fan_auto_box = QtWidgets.QCheckBox(parent=self.fan_group)
        self.fan_auto_box.setMinimumSize(QtCore.QSize(70, 0))
        self.fan_auto_box.setMaximumSize(QtCore.QSize(70, 16777215))
        self.fan_layout.addWidget(self.fan_auto_box)
        self.fan_pwm_warning = QtWidgets.QLabel(parent=self.fan_group)
        self.fan_pwm_warning.setMinimumSize(QtCore.QSize(16, 0))
        self.fan_layout.addWidget(self.fan_pwm_warning)

        self.fan_power_slider.valueChanged.connect(self.fan_set)
        self.fan_auto_box.stateChanged.connect(self.fan_auto_set)

        self.fan_lbl.setToolTip("Adjust the fan")
        self.fan_lbl.setText("Fan:")
        self.fan_auto_box.setText("Auto")

        fan = QtWidgets.QWidgetAction(self.thermostat_menu)
        fan.setDefaultWidget(self.fan_group)
        self.thermostat_menu.addAction(fan)
        self.thermostat_menu.fan = fan

        @asyncSlot(bool)
        async def reset_thermostat(_):
            await self._on_connection_changed(False)
            await self.client.reset()
            await asyncio.sleep(0.1) # Wait for the reset to start

            self.connect_btn.click() # Reconnect

        self.actionReset.triggered.connect(reset_thermostat)
        self.thermostat_menu.addAction(self.actionReset)

        @asyncSlot(bool)
        async def dfu_mode(_):
            await self._on_connection_changed(False)
            await self.client.dfu()

            # TODO: add a firmware flashing GUI?

        self.actionEnter_DFU_Mode.triggered.connect(dfu_mode)
        self.thermostat_menu.addAction(self.actionEnter_DFU_Mode)

        @asyncSlot(bool)
        async def network_settings(_):
            ask_network = QtWidgets.QInputDialog(self)
            ask_network.setWindowTitle("Network Settings")
            ask_network.setLabelText("Set the Thermostat's IPv4 address, netmask and gateway (optional)")
            ask_network.setTextValue((await self.client.ipv4())['addr'])

            @pyqtSlot(str)
            def set_ipv4(ipv4_settings):
                sure = QtWidgets.QMessageBox(self)
                sure.setWindowTitle("Set network?")
                sure.setText(f"Setting this as network and disconnecting:<br>{ipv4_settings}")

                @asyncSlot(object)
                async def really_set(button):
                    await self.client.set_param("ipv4", ipv4_settings)
                    await self.client.disconnect()

                    await self._on_connection_changed(False)

                sure.buttonClicked.connect(really_set)
                sure.show()
            ask_network.textValueSelected.connect(set_ipv4)
            ask_network.show()

        self.actionNetwork_Settings.triggered.connect(network_settings)
        self.thermostat_menu.addAction(self.actionNetwork_Settings)

        @asyncSlot(bool)
        async def load(_):
            await self.client.load_config()
            loaded = QtWidgets.QMessageBox(self)
            loaded.setWindowTitle("Config loaded")
            loaded.setText(f"All channel configs have been loaded from flash.")
            loaded.setIcon(QtWidgets.QMessageBox.Icon.Information)
            loaded.show()

        self.actionLoad_all_configs.triggered.connect(load)
        self.thermostat_menu.addAction(self.actionLoad_all_configs)

        @asyncSlot(bool)
        async def save(_):
            await self.client.save_config()
            saved = QtWidgets.QMessageBox(self)
            saved.setWindowTitle("Config saved")
            saved.setText(f"All channel configs have been saved to flash.")
            saved.setIcon(QtWidgets.QMessageBox.Icon.Information)
            saved.show()

        self.actionSave_all_configs.triggered.connect(save)
        self.thermostat_menu.addAction(self.actionSave_all_configs)

        def about_thermostat():
            QtWidgets.QMessageBox.about(
                self,
                "About Thermostat",
                f"""
                <h1>Sinara 8451 Thermostat v{self.hw_rev_data['rev']['major']}.{self.hw_rev_data['rev']['minor']}</h1>

                <br>

                <h2>Settings:</h2>
                Default fan curve:
                    a = {self.hw_rev_data['settings']['fan_k_a']},
                    b = {self.hw_rev_data['settings']['fan_k_b']},
                    c = {self.hw_rev_data['settings']['fan_k_c']}
                <br>
                Fan PWM range: 
                    {self.hw_rev_data['settings']['min_fan_pwm']} \u2013 {self.hw_rev_data['settings']['max_fan_pwm']}
                <br>
                Fan PWM frequency: {self.hw_rev_data['settings']['fan_pwm_freq_hz']} Hz
                <br>
                Fan available: {self.hw_rev_data['settings']['fan_available']}
                <br>
                Fan PWM recommended: {self.hw_rev_data['settings']['fan_pwm_recommended']}
                """
            )

        self.actionAbout_Thermostat.triggered.connect(about_thermostat)
        self.thermostat_menu.addAction(self.actionAbout_Thermostat)

        self.thermostat_settings.setMenu(self.thermostat_menu)

    def _set_up_plot_menu(self):
        self.plot_menu = QtWidgets.QMenu()
        self.plot_menu.setTitle("Plot Settings")

        clear = QtGui.QAction("Clear graphs", self.plot_menu)
        clear.triggered.connect(self.clear_graphs)
        self.plot_menu.addAction(clear)
        self.plot_menu.clear = clear

        self.samples_spinbox = QtWidgets.QSpinBox()
        self.samples_spinbox.setRange(2, 100000)
        self.samples_spinbox.setSuffix(' samples')
        self.samples_spinbox.setValue(self.max_samples)
        self.samples_spinbox.valueChanged.connect(self.set_max_samples)

        limit_samples = QtWidgets.QWidgetAction(self.plot_menu)
        limit_samples.setDefaultWidget(self.samples_spinbox)
        self.plot_menu.addAction(limit_samples)
        self.plot_menu.limit_samples = limit_samples

        self.plot_settings.setMenu(self.plot_menu)

    @pyqtSlot(list)
    def set_limits_warning(self, channels_zeroed_limits: list):
        channel_disabled = [False, False]

        report_str = "The following output limit(s) are set to zero:\n"
        for ch, zeroed_limits in enumerate(channels_zeroed_limits):
            if {'max_i_pos', 'max_i_neg'}.issubset(zeroed_limits):
                report_str += "Max Cooling Current, Max Heating Current"
                channel_disabled[ch] = True

            if 'max_v' in zeroed_limits:
                if channel_disabled[ch]:
                    report_str += ", "
                report_str += "Max Voltage Difference"
                channel_disabled[ch] = True

            if channel_disabled[ch]:
                report_str += f" for Channel {ch}\n"

        report_str += "\nThese limit(s) are restricting the channel(s) from producing current."

        if True in channel_disabled:
            pixmapi = getattr(QtWidgets.QStyle.StandardPixmap, "SP_MessageBoxWarning")
            icon = self.style().standardIcon(pixmapi)
            self.limits_warning.setPixmap(icon.pixmap(16, 16))
            self.limits_warning.setToolTip(report_str)
        else:
            self.limits_warning.setPixmap(QtGui.QPixmap())
            self.limits_warning.setToolTip(None)

    @pyqtSlot(int)
    def set_max_samples(self, samples: int):
        for channel_graph in self.channel_graphs:
            channel_graph.t_connector.max_points = samples
            channel_graph.i_connector.max_points = samples
            channel_graph.iset_connector.max_points = samples

    def clear_graphs(self):
        for channel_graph in self.channel_graphs:
            channel_graph.clear()

    async def _on_connection_changed(self, result):
        self.graph_group.setEnabled(result)
        self.report_group.setEnabled(result)
        self.thermostat_settings.setEnabled(result)

        self.host_set_line.setEnabled(not result)
        self.port_set_spin.setEnabled(not result)
        self.connect_btn.setText("Disconnect" if result else "Connect")
        if result:
            self.hw_rev_data = await self.client.hw_rev()
            self._status(self.hw_rev_data)
            self.client_watcher.start_watching()
            # await self.client.set_param("fan", 1)
        else:
            self.status_lbl.setText("Disconnected")
            self.fan_pwm_warning.setPixmap(QtGui.QPixmap())
            self.fan_pwm_warning.setToolTip("")
            self.clear_graphs()
            self.report_box.setChecked(False)
            await self.client_watcher.set_report_mode(False)
            self.client_watcher.stop_watching()
            self.status_lbl.setText("Disconnected")

    def _set_fan_pwm_warning(self):
        if self.fan_power_slider.value() != 100:
            pixmapi = getattr(QtWidgets.QStyle.StandardPixmap, "SP_MessageBoxWarning")
            icon = self.style().standardIcon(pixmapi)
            self.fan_pwm_warning.setPixmap(icon.pixmap(16, 16))
            self.fan_pwm_warning.setToolTip("Throttling the fan (not recommended on this hardware rev)")
        else:
            self.fan_pwm_warning.setPixmap(QtGui.QPixmap())
            self.fan_pwm_warning.setToolTip("")

    def _status(self, hw_rev_d: dict):
        logging.debug(hw_rev_d)
        self.status_lbl.setText(f"Connected to Thermostat v{hw_rev_d['rev']['major']}.{hw_rev_d['rev']['minor']}")
        self.fan_group.setEnabled(hw_rev_d["settings"]["fan_available"])

    @pyqtSlot(dict)
    def fan_update(self, fan_settings: dict):
        logging.debug(fan_settings)
        if fan_settings is None:
            return
        with QSignalBlocker(self.fan_power_slider):
            self.fan_power_slider.setValue(fan_settings["fan_pwm"] or 100) # 0 = PWM off = full strength
        with QSignalBlocker(self.fan_auto_box):
            self.fan_auto_box.setChecked(fan_settings["auto_mode"])
        if not self.hw_rev_data["settings"]["fan_pwm_recommended"]:
            self._set_fan_pwm_warning()

    @asyncSlot(int)
    async def fan_set(self, value):
        if not self.client.connected():
            return
        if self.fan_auto_box.isChecked():
            with QSignalBlocker(self.fan_auto_box):
                self.fan_auto_box.setChecked(False)
        await self.client.set_fan(value)
        if not self.hw_rev_data["settings"]["fan_pwm_recommended"]:
            self._set_fan_pwm_warning()

    @asyncSlot(int)
    async def fan_auto_set(self, enabled):
        if not self.client.connected():
            return
        if enabled:
            await self.client.set_fan("auto")
            self.fan_update(await self.client.get_fan())
        else:
            await self.client.set_fan(self.fan_power_slider.value())

    @asyncSlot(int)
    async def on_report_box_stateChanged(self, enabled):
        await self.client_watcher.set_report_mode(enabled)

    @asyncClose
    async def closeEvent(self, event):
        await self.bail()

    @asyncSlot()
    async def on_connect_btn_clicked(self):
        host, port = self.host_set_line.text(), self.port_set_spin.value()
        try:
            if not (self.client.connecting() or self.client.connected()):
                self.status_lbl.setText("Connecting...")
                self.connect_btn.setText("Stop")
                self.host_set_line.setEnabled(False)
                self.port_set_spin.setEnabled(False)

                try:
                    await self.client.start_session(host=host, port=port, timeout=30)
                except StoppedConnecting:
                    return
                await self._on_connection_changed(True)
            else:
                await self.bail()

        except (OSError, TimeoutError, asyncio.TimeoutError) as e: # TODO: Remove asyncio.TimeoutError in Python 3.11
            logging.error(f"Failed communicating to {host}:{port}: {e}")
            await self.bail()

    @asyncSlot()
    async def bail(self):
        await self._on_connection_changed(False)
        await self.client.end_session()

    @asyncSlot(object, object)
    async def send_command(self, param, changes):
        """Translates parameter tree changes into thermostat set_param calls"""

        for inner_param, change, data in changes:
            if change == 'value':
                if inner_param.opts.get("param", None) is not None:
                    if 'Current' in inner_param.name():
                        data /= 1000 # Given in mA

                    thermostat_param = inner_param.opts["param"]
                    if inner_param.name() == 'Postfilter Rate' and data == None:
                        set_param_args = (*thermostat_param[:2], 'off')
                    else:
                        set_param_args = (*thermostat_param, data)
                    await self.client.set_param(*set_param_args)
                if inner_param.opts.get('activaters', None) is not None:
                    activater = inner_param.opts['activaters'][inner_param.opts['limits'].index(data)]
                    if activater is not None:
                        await self.client.set_param(*activater)


    def _set_param_tree(self):
        for i, tree in enumerate((self.ch0_tree, self.ch1_tree)):
            tree.setHeaderHidden(True)
            tree.setParameters(self.params[i], showTop=False)
            self.params[i].sigTreeStateChanged.connect(self.send_command)

            @asyncSlot()
            async def save(_, ch=i):
                await self.client.save_config(ch)
                saved = QtWidgets.QMessageBox(self)
                saved.setWindowTitle("Config saved")
                saved.setText(f"Channel {ch} Config has been saved to flash.")
                saved.setIcon(QtWidgets.QMessageBox.Icon.Information)
                saved.show()

            self.params[i].child('Save to flash').sigActivated.connect(save)

            @asyncSlot()
            async def load(_, ch=i):
                await self.client.load_config(ch)
                loaded = QtWidgets.QMessageBox(self)
                loaded.setWindowTitle("Config loaded")
                loaded.setText(f"Channel {ch} Config has been loaded from flash.")
                loaded.setIcon(QtWidgets.QMessageBox.Icon.Information)
                loaded.show()

            self.params[i].child('Load from flash').sigActivated.connect(load)

            @asyncSlot()
            async def autotune(param, ch=i):
                match self.autotuners[ch].state():
                    case PIDAutotuneState.STATE_OFF:
                        self.autotuners[ch].setParam(
                            param.parent().child('Target Temperature').value(),
                            param.parent().child('Test Current').value() / 1000,
                            param.parent().child('Temperature Swing').value(),
                            self.report_refresh_spin.value(),
                            3)
                        self.autotuners[ch].setReady()
                        param.setOpts(title="Stop")
                        self.client_watcher.report_update.connect(self.autotune_tick)
                        self.loading_spinner.show()
                        self.loading_spinner.start()
                        if self.autotuners[1 - ch].state() == PIDAutotuneState.STATE_OFF:
                            self.background_task_lbl.setText("Autotuning channel {ch}...".format(ch=ch))
                        else:
                            self.background_task_lbl.setText("Autotuning channel 0 and 1...")
                    case PIDAutotuneState.STATE_READY | PIDAutotuneState.STATE_RELAY_STEP_UP | PIDAutotuneState.STATE_RELAY_STEP_DOWN:
                        self.autotuners[ch].setOff()
                        param.setOpts(title="Run")
                        await self.client.set_param('pwm', ch, 'i_set', 0)
                        self.client_watcher.report_update.disconnect(self.autotune_tick)
                        if self.autotuners[1 - ch].state() == PIDAutotuneState.STATE_OFF:
                            self.background_task_lbl.setText("Ready.")
                            self.loading_spinner.stop()
                            self.loading_spinner.hide()
                        else:
                            self.background_task_lbl.setText("Autotuning channel {ch}...".format(ch=1-ch))

            self.params[i].child('PID Config', 'PID Auto Tune', 'Run').sigActivated.connect(autotune)

    @asyncSlot(list)
    async def autotune_tick(self, report):
        for channel_report in report:
            channel = channel_report['channel']
            match self.autotuners[channel].state():
                case PIDAutotuneState.STATE_READY | PIDAutotuneState.STATE_RELAY_STEP_UP | PIDAutotuneState.STATE_RELAY_STEP_DOWN:
                    self.autotuners[channel].run(channel_report['temperature'], channel_report['time'])
                    await self.client.set_param('pwm', channel, 'i_set', self.autotuners[channel].output())
                case PIDAutotuneState.STATE_SUCCEEDED:
                    kp, ki, kd = self.autotuners[channel].get_tec_pid()
                    self.autotuners[channel].setOff()
                    self.params[channel].child('PID Config', 'PID Auto Tune', 'Run').setOpts(title="Run")
                    await self.client.set_param('pid', channel, 'kp', kp)
                    await self.client.set_param('pid', channel, 'ki', ki)
                    await self.client.set_param('pid', channel, 'kd', kd)
                    await self.client.set_param('pwm', channel, 'pid')
                    await self.client.set_param('pid', channel, 'target', self.params[channel].child("PID Config", "PID Auto Tune", "Target Temperature").value())
                    self.client_watcher.report_update.disconnect(self.autotune_tick)
                    if self.autotuners[1 - channel].state() == PIDAutotuneState.STATE_OFF:
                        self.background_task_lbl.setText("Ready.")
                        self.loading_spinner.stop()
                        self.loading_spinner.hide()
                    else:
                        self.background_task_lbl.setText("Autotuning channel {ch}...".format(ch=1-ch))
                case PIDAutotuneState.STATE_FAILED:
                    self.autotuners[channel].setOff()
                    self.params[channel].child('PID Config', 'PID Auto Tune', 'Run').setOpts(title="Run")
                    await self.client.set_param('pwm', channel, 'i_set', 0)
                    self.client_watcher.report_update.disconnect(self.autotune_tick)
                    if self.autotuners[1 - channel].state() == PIDAutotuneState.STATE_OFF:
                        self.background_task_lbl.setText("Ready.")
                        self.loading_spinner.stop()
                        self.loading_spinner.hide()
                    else:
                        self.background_task_lbl.setText("Autotuning channel {ch}...".format(ch=1-ch))

    @pyqtSlot(list)
    def update_pid(self, pid_settings):
        for settings in pid_settings:
            channel = settings["channel"]
            with QSignalBlocker(self.params[channel]):
                self.params[channel].child("PID Config", "Kp").setValue(settings["parameters"]["kp"])
                self.params[channel].child("PID Config", "Ki").setValue(settings["parameters"]["ki"])
                self.params[channel].child("PID Config", "Kd").setValue(settings["parameters"]["kd"])
                self.params[channel].child("PID Config", "PID Output Clamping", "Minimum").setValue(settings["parameters"]["output_min"] * 1000)
                self.params[channel].child("PID Config", "PID Output Clamping", "Maximum").setValue(settings["parameters"]["output_max"] * 1000)
                self.params[channel].child("Output Config", "Control Method", "Set Temperature").setValue(settings["target"])
                self.channel_graphs[channel].set_t_line(temp=round(settings["target"], 6))

    @pyqtSlot(list)
    def update_report(self, report_data):
        for settings in report_data:
            channel = settings["channel"]
            self.channel_graphs[channel].plot_append(settings)
            with QSignalBlocker(self.params[channel]):
                self.params[channel].child("Output Config", "Control Method").setValue("Temperature PID" if settings["pid_engaged"] else "Constant Current")
                self.channel_graphs[channel].set_t_line(visible=settings['pid_engaged'])
                self.params[channel].child("Output Config", "Control Method", "Set Current").setValue(settings["i_set"] * 1000)
                if settings['temperature'] is not None:
                    self.params[channel].child("Temperature").setValue(settings['temperature'])
                    if settings['tec_i'] is not None:
                        self.params[channel].child("Current through TEC").setValue(settings['tec_i'] * 1000)

    @pyqtSlot(list)
    def update_thermistor(self, sh_data):
        for sh_param in sh_data:
            channel = sh_param["channel"]
            with QSignalBlocker(self.params[channel]):
                self.params[channel].child("Thermistor Config", "T₀").setValue(sh_param["params"]["t0"] - 273.15)
                self.params[channel].child("Thermistor Config", "R₀").setValue(sh_param["params"]["r0"])
                self.params[channel].child("Thermistor Config", "B").setValue(sh_param["params"]["b"])

    @pyqtSlot(list)
    def update_pwm(self, pwm_data):
        channels_zeroed_limits = [set() for i in range(NUM_CHANNELS)]

        for pwm_params in pwm_data:
            channel = pwm_params["channel"]
            with QSignalBlocker(self.params[channel]):
                self.params[channel].child("Output Config", "Limits", "Max Voltage Difference").setValue(pwm_params["max_v"]["value"])
                self.params[channel].child("Output Config", "Limits", "Max Cooling Current").setValue(pwm_params["max_i_pos"]["value"] * 1000)
                self.params[channel].child("Output Config", "Limits", "Max Heating Current").setValue(pwm_params["max_i_neg"]["value"] * 1000)

            for limit in "max_i_pos", "max_i_neg", "max_v":
                if pwm_params[limit]["value"] == 0.0:
                    channels_zeroed_limits[channel].add(limit)

        self.set_limits_warning(channels_zeroed_limits)

    @pyqtSlot(list)
    def update_postfilter(self, postfilter_data):
        for postfilter_params in postfilter_data:
            channel = postfilter_params["channel"]
            with QSignalBlocker(self.params[channel]):
                self.params[channel].child("Thermistor Config", "Postfilter Rate").setValue(postfilter_params["rate"])


async def coro_main():
    args = get_argparser().parse_args()
    if args.logLevel:
        logging.basicConfig(level=getattr(logging, args.logLevel))

    app_quit_event = asyncio.Event()

    app = QtWidgets.QApplication.instance()
    app.aboutToQuit.connect(app_quit_event.set)

    main_window = MainWindow(args)
    main_window.show()

    await app_quit_event.wait()


def main():
    qasync.run(coro_main())


if __name__ == '__main__':
    main()
