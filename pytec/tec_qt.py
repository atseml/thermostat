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
