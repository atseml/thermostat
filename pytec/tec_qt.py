from PyQt6 import QtWidgets, uic
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

tec_client: Client = None

# ui = None
ui: Ui_MainWindow = None

client_watcher = None
client_watcher_task = None
app: QtWidgets.QApplication = None


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
    fan_update = pyqtSignal(object)
    pwm_update = pyqtSignal(object)
    report_update = pyqtSignal(object)
    pid_update = pyqtSignal(object)

    def __init__(self, parent, update_s):
        self.update_s = update_s
        self.running = True
        super().__init__(parent)

    async def run(self):
        while self.running:
            await self.update_params()
            await asyncio.sleep(self.update_s)

    async def update_params(self):
        self.fan_update.emit(await tec_client.fan())

    @pyqtSlot()
    def stop_watching(self):
        self.running = False

    @pyqtSlot()
    def set_update_s(self):
        self.update_s = ui.report_refresh_spin.value()


def on_connection_changed(result):
    global client_watcher, client_watcher_task
    ui.graph_group.setEnabled(result)
    ui.hw_rev_lbl.setEnabled(result)
    ui.fan_group.setEnabled(result)
    ui.report_group.setEnabled(result)

    ui.ip_set_line.setEnabled(not result)
    ui.port_set_spin.setEnabled(not result)
    ui.status_lbl.setText("Connected" if result else "Disconnected")
    ui.connect_btn.setText("Disconnect" if result else "Connect")
    if not result:
        ui.hw_rev_lbl.setText("Thermostat vX.Y")
        ui.fan_group.setStyleSheet("")
        if client_watcher:
            client_watcher.stop_watching()
            client_watcher = None
            client_watcher_task = None


def hw_rev(hw_rev_d: dict):
    logging.debug(hw_rev_d)
    ui.hw_rev_lbl.setText(f"Thermostat v{hw_rev_d['rev']['major']}.{hw_rev_d['rev']['major']}")
    ui.fan_group.setEnabled(hw_rev_d["settings"]["fan_available"])
    if hw_rev_d["settings"]["fan_pwm_recommended"]:
        ui.fan_group.setStyleSheet("")
        ui.fan_group.setToolTip("")
    else:
        ui.fan_group.setStyleSheet("background-color: yellow")
        ui.fan_group.setToolTip("Changing the fan settings of not recommended")


def fan_update(fan_settings):
    logging.debug(fan_settings)
    if fan_settings is None:
        return
    with QSignalBlocker(ui.fan_power_slider) as _:
        ui.fan_power_slider.setValue(fan_settings["fan_pwm"])
        ui.fan_power_slider.setEnabled(not fan_settings["auto_mode"])
    with QSignalBlocker(ui.fan_auto_box) as _:
        ui.fan_auto_box.setChecked(fan_settings["auto_mode"])


@asyncSlot()
async def fan_set(_):
    global tec_client
    if tec_client is None or ui.fan_auto_box.isChecked():
        return
    await tec_client.set_param("fan", ui.fan_power_slider.value())


@asyncSlot()
async def fan_auto_set(enabled):
    global tec_client
    if tec_client is None:
        return
    ui.fan_power_slider.setEnabled(not enabled)
    if enabled:
        await tec_client.set_param("fan", "auto")
    else:
        await tec_client.set_param("fan", ui.fan_power_slider.value())


@asyncSlot()
async def connect(_):
    global tec_client, client_watcher, client_watcher_task
    ip, port = ui.ip_set_line.text(), ui.port_set_spin.value()
    try:
        if tec_client:
            await tec_client.disconnect()
            tec_client = None
            on_connection_changed(False)
        else:
            ui.status_lbl.setText("Connecting...")
            tec_client = Client()
            await tec_client.connect(host=ip, port=port, timeout=30)
            on_connection_changed(True)
            hw_rev(await tec_client.hw_rev())
            # fan_update(await tec_client.fan())
            if client_watcher is None:
                client_watcher = ClientWatcher(ui.main_widget, ui.report_refresh_spin.value())
                client_watcher.fan_update.connect(fan_update)
                ui.report_apply_btn.clicked.connect(
                    lambda: client_watcher.set_update_s(ui.report_refresh_spin.value())
                )
                app.aboutToQuit.connect(client_watcher.stop_watching)
                client_watcher_task = asyncio.create_task(client_watcher.run())
    except Exception as e:
        logging.error(f"Failed communicating to the {ip}:{port}: {e}")
        on_connection_changed(False)


async def coro_main():
    global ui, app

    args = get_argparser().parse_args()
    if args.logLevel:
        logging.basicConfig(level=getattr(logging, args.logLevel))

    app_quit_event = asyncio.Event()

    app = QtWidgets.QApplication.instance()
    app.aboutToQuit.connect(app_quit_event.set)

    main_window = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(main_window)
    # ui = uic.loadUi('tec_qt.ui', main_window)

    ui.connect_btn.clicked.connect(connect)
    ui.fan_power_slider.valueChanged.connect(fan_set)
    ui.fan_auto_box.stateChanged.connect(fan_auto_set)

    if args.connect:
        if args.IP:
            ui.ip_set_line.setText(args.IP)
        if args.PORT:
            ui.port_set_spin.setValue(int(args.PORT))
        ui.connect_btn.click()

    main_window.show()

    await app_quit_event.wait()


def main():
    qasync.run(coro_main())


if __name__ == '__main__':
    main()
