from PyQt6 import QtWidgets, QtGui
from PyQt6.QtCore import pyqtSignal, QObject, QSignalBlocker, pyqtSlot
from pyqtgraph import PlotWidget
from pyqtgraph.parametertree import Parameter, ParameterTree, ParameterItem, registerParameterType
import pyqtgraph as pg
import sys
import argparse
import logging
import asyncio
from pytec.aioclient import Client
import qasync
from qasync import asyncSlot, asyncClose

# pyuic6 -x tec_qt.ui  -o ui_tec_qt.py
from ui_tec_qt import Ui_MainWindow


class CommandsParameter(Parameter):
    def __init__(self, **opts):
        super().__init__()
        self.opts["commands"] = opts.get("commands", None)
        self.opts["payload"] = opts.get("payload", None)


ThermostatParams = [[
    {'name': 'Constant Current', 'type': 'float', 'value': 0, 'step': 0.1, 'limits': (-3, 3), 'siPrefix': True,
     'suffix': 'A', 'commands': [f'pwm {ch} i_set {{value}}']},
    {'name': 'Temperature PID', 'type': 'bool', 'value': False, 'commands': [f'pwm {ch} pid'], 'payload': ch,
     'children': [
         {'name': 'Set Temperature', 'type': 'float', 'value': 25, 'step': 0.1, 'limits': (-273, 300), 'siPrefix': True,
          'suffix': '°C', 'commands': [f'pid {ch} target {{value}}']},
     ]},
    {'name': 'Output Config', 'expanded': False, 'type': 'group', 'children': [
        {'name': 'Max Current', 'type': 'float', 'value': 0, 'step': 0.1, 'limits': (0, 3), 'siPrefix': True,
         'suffix': 'A', 'commands': [f'pwm {ch} max_i_pos {{value}}', f'pwm {ch} max_i_neg {{value}}',
                                     f'pid {ch} output_min -{{value}}', f'pid {ch} output_max {{value}}']},
        {'name': 'Max Voltage', 'type': 'float', 'value': 0, 'step': 0.1, 'limits': (0, 5), 'siPrefix': True,
         'suffix': 'V', 'commands': [f'pwm {ch} max_v {{value}}']},
    ]},
    {'name': 'Thermistor Config', 'expanded': False, 'type': 'group', 'children': [
        {'name': 'T0', 'type': 'float', 'value': 25, 'step': 0.1, 'limits': (-100, 100), 'siPrefix': True,
         'suffix': 'C', 'commands': [f's-h {ch} t0 {{value}}']},
        {'name': 'R0', 'type': 'float', 'value': 10000, 'step': 1, 'siPrefix': True, 'suffix': 'Ohm',
         'commands': [f's-h {ch} r0 {{value}}']},
        {'name': 'Beta', 'type': 'float', 'value': 3950, 'step': 1, 'commands': [f's-h {ch} b {{value}}']},
    ]},
    {'name': 'PID Config', 'expanded': False, 'type': 'group', 'children': [
        {'name': 'kP', 'type': 'float', 'value': 0, 'step': 0.1, 'commands': [f'pid {ch} kp {{value}}']},
        {'name': 'kI', 'type': 'float', 'value': 0, 'step': 0.1, 'commands': [f'pid {ch} ki {{value}}']},
        {'name': 'kD', 'type': 'float', 'value': 0, 'step': 0.1, 'commands': [f'pid {ch} kd {{value}}']},
        {'name': 'PID Auto Tune', 'expanded': False, 'type': 'group', 'children': [
            {'name': 'Target Temperature', 'type': 'float', 'value': 20, 'step': 0.1, 'siPrefix': True, 'suffix': 'C'},
            {'name': 'Test Current', 'type': 'float', 'value': 1, 'step': 0.1, 'siPrefix': True, 'suffix': 'A'},
            {'name': 'Temperature Swing', 'type': 'float', 'value': 1.5, 'step': 0.1, 'siPrefix': True, 'suffix': 'C'},
            {'name': 'Run', 'type': 'action', 'tip': 'Run'},
        ]},
    ]}
] for ch in range(2)]

params = [CommandsParameter.create(name='Thermostat Params 0', type='group', children=ThermostatParams[0]),
          CommandsParameter.create(name='Thermostat Params 1', type='group', children=ThermostatParams[1])]


def get_argparser():
    parser = argparse.ArgumentParser(description="ARTIQ master")

    parser.add_argument("--connect", default=None, action="store_true",
                        help="Automatically connect to the specified Thermostat in IP:port format")
    parser.add_argument('IP', metavar="ip", default=None, nargs='?')
    parser.add_argument('PORT', metavar="port", default=None, nargs='?')
    parser.add_argument("-l", "--log", dest="logLevel", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help="Set the logging level")

    return parser


class ClientWatcher(QObject):
    fan_update = pyqtSignal(dict)
    pwm_update = pyqtSignal(list)
    report_update = pyqtSignal(list)
    pid_update = pyqtSignal(list)

    def __init__(self, parent, client, update_s):
        self.update_s = update_s
        self.client = client
        self.watch_task = None
        super().__init__(parent)

    async def run(self):
        loop = asyncio.get_running_loop()
        while True:
            time = loop.time()
            await self.update_params()
            await asyncio.sleep(self.update_s - (loop.time() - time))

    async def update_params(self):
        self.fan_update.emit(await self.client.fan())
        self.pwm_update.emit(await self.client.get_pwm())
        self.report_update.emit(await self.client._command("report"))
        self.pid_update.emit(await self.client.get_pid())

    def start_watching(self):
        self.watch_task = asyncio.create_task(self.run())

    def is_watching(self):
        return self.watch_task is not None

    @pyqtSlot()
    def stop_watching(self):
        if self.watch_task is not None:
            self.watch_task.cancel()
            self.watch_task = None

    @pyqtSlot(float)
    def set_update_s(self, update_s):
        self.update_s = update_s


class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self, args):
        super().__init__()

        self.setupUi(self)

        self._set_up_context_menu()

        self.fan_power_slider.valueChanged.connect(self.fan_set)
        self.fan_auto_box.stateChanged.connect(self.fan_auto_set)

        self._set_param_tree()

        self.fan_pwm_recommended = False

        self.tec_client = Client()
        self.client_watcher = ClientWatcher(self, self.tec_client, self.report_refresh_spin.value())
        self.client_watcher.fan_update.connect(self.fan_update)
        self.report_apply_btn.clicked.connect(
            lambda: self.client_watcher.set_update_s(self.report_refresh_spin.value())
        )

        if args.connect:
            if args.IP:
                self.ip_set_line.setText(args.IP)
            if args.PORT:
                self.port_set_spin.setValue(int(args.PORT))
            self.connect_btn.click()

    def _set_up_context_menu(self):
        self.menu = QtWidgets.QMenu()
        self.menu.setTitle('Thermostat settings')

        port = QtWidgets.QWidgetAction(self.menu)
        port.setDefaultWidget(self.port_set_spin)
        self.menu.addAction(port)
        self.menu.port = port

        fan = QtWidgets.QWidgetAction(self.menu)
        fan.setDefaultWidget(self.fan_group)
        self.menu.addAction(fan)
        self.menu.fan = fan

        self.thermostat_settings.setMenu(self.menu)

    async def _on_connection_changed(self, result):
        self.graph_group.setEnabled(result)
        self.fan_group.setEnabled(result)
        self.report_group.setEnabled(result)

        self.ip_set_line.setEnabled(not result)
        self.port_set_spin.setEnabled(not result)
        self.connect_btn.setText("Disconnect" if result else "Connect")
        if result:
            self.client_watcher.start_watching()
            self._status(await self.tec_client.hw_rev())
            self.fan_update(await self.tec_client.fan())
        else:
            self.status_lbl.setText("Disconnected")
            self.fan_pwm_warning.setPixmap(QtGui.QPixmap())
            self.fan_pwm_warning.setToolTip("")
            self.client_watcher.stop_watching()

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
        self.fan_pwm_recommended = hw_rev_d["settings"]["fan_pwm_recommended"]

    @pyqtSlot(dict)
    def fan_update(self, fan_settings: dict):
        logging.debug(fan_settings)
        if fan_settings is None:
            return
        with QSignalBlocker(self.fan_power_slider):
            self.fan_power_slider.setValue(fan_settings["fan_pwm"] or 100) # 0 = PWM off = full strength
        with QSignalBlocker(self.fan_auto_box):
            self.fan_auto_box.setChecked(fan_settings["auto_mode"])
        if not self.fan_pwm_recommended:
            self._set_fan_pwm_warning()

    @asyncSlot(int)
    async def fan_set(self, value):
        if not self.tec_client.is_connected():
            return
        if self.fan_auto_box.isChecked():
            with QSignalBlocker(self.fan_auto_box):
                self.fan_auto_box.setChecked(False)
        await self.tec_client.set_param("fan", value)
        if not self.fan_pwm_recommended:
            self._set_fan_pwm_warning()

    @asyncSlot(int)
    async def fan_auto_set(self, enabled):
        if not self.tec_client.is_connected():
            return
        if enabled:
            await self.tec_client.set_param("fan", "auto")
            self.fan_update(await self.tec_client.fan())
        else:
            await self.tec_client.set_param("fan", self.fan_power_slider.value())

    @asyncClose
    async def closeEvent(self, event):
        self.client_watcher.stop_watching()
        await self.tec_client.disconnect()

    @asyncSlot()
    async def on_connect_btn_clicked(self):
        ip, port = self.ip_set_line.text(), self.port_set_spin.value()
        try:
            if not (self.tec_client.is_connecting() or self.tec_client.is_connected()):
                self.status_lbl.setText("Connecting...")
                self.connect_btn.setText("Stop")
                self.ip_set_line.setEnabled(False)
                self.port_set_spin.setEnabled(False)

                connected = await self.tec_client.connect(host=ip, port=port, timeout=30)
                if not connected:
                    return
                await self._on_connection_changed(True)
            else:
                await self._on_connection_changed(False)
                await self.tec_client.disconnect()

        except (OSError, TimeoutError) as e:
            logging.error(f"Failed communicating to {ip}:{port}: {e}")
            await self._on_connection_changed(False)
            await self.tec_client.disconnect()

    @asyncSlot(object, object)
    async def send_command(self, param, changes):
        for param, change, data in changes:
            if param.name() == 'Temperature PID' and not data:
                ch = param.opts["payload"]
                await self.tec_client.set_param('pwm', ch, 'i_set', params[ch].child('Constant Current').value())
            elif param.opts.get("commands", None) is not None:
                await asyncio.gather(*[self.tec_client._command(x.format(value=data)) for x in param.opts["commands"]])

    def _set_param_tree(self):
        self.ch0_tree.setParameters(params[0], showTop=False)
        self.ch1_tree.setParameters(params[1], showTop=False)
        params[0].sigTreeStateChanged.connect(self.send_command)
        params[1].sigTreeStateChanged.connect(self.send_command)

    @pyqtSlot(list)
    def update_pid(self, pid_settings):
        for settings in pid_settings:
            channel = settings["channel"]
            with QSignalBlocker(params[channel]) as _:
                params[channel].child("PID Config", "kP").setValue(settings["parameters"]["kp"])
                params[channel].child("PID Config", "kI").setValue(settings["parameters"]["ki"])
                params[channel].child("PID Config", "kD").setValue(settings["parameters"]["kd"])
                if params[channel].child("Temperature PID").value():
                    params[channel].child("Temperature PID", "Set Temperature").setValue(settings["target"])

    @pyqtSlot(list)
    def update_report(self, report_data):
        for settings in report_data:
            channel = settings["channel"]
            with QSignalBlocker(params[channel]) as _:
                params[channel].child("Temperature PID").setValue(settings["pid_engaged"])


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
