from PyQt6 import QtWidgets, uic
from PyQt6.QtCore import QThread, QThreadPool, pyqtSignal, QRunnable, QObject, QSignalBlocker, pyqtSlot, QDeadlineTimer
from pyqtgraph import PlotWidget
from pyqtgraph.parametertree import Parameter, ParameterTree, ParameterItem, registerParameterType
import pyqtgraph as pg
import sys
import argparse
import logging
from pytec.client import Client

# pyuic6 -x tec_qt.ui  -o ui_tec_qt.py
from ui_tec_qt import Ui_MainWindow

tec_client: Client = None

# ui = None
ui: Ui_MainWindow = None

thread_pool = QThreadPool.globalInstance()
connection_watcher = None
client_watcher = None
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


class WatchConnectTask(QThread):
    connected = pyqtSignal(bool)
    hw_rev = pyqtSignal(dict)
    connecting = pyqtSignal()
    fan_update = pyqtSignal(object)

    def __init__(self, parent, ip, port):
        self.ip = ip
        self.port = port
        super().__init__(parent)

    def run(self):
        global tec_client
        try:
            if tec_client:
                tec_client.disconnect()
                tec_client = None
                self.connected.emit(False)
            else:
                self.connecting.emit()
                tec_client = Client(host=self.ip, port=self.port, timeout=30)
                self.connected.emit(True)
                thread_pool.start(ClientTask(lambda: self.hw_rev.emit(tec_client.hw_rev())))
                #thread_pool.start(ClientTask(lambda: self.fan_update.emit(tec_client.fan())))
        except Exception as e:
            logging.error(f"Failed communicating to the {self.ip}:{self.port}: {e}")
            self.connected.emit(False)

    @pyqtSlot()
    def client_disconnected(self):
        global tec_client
        if tec_client:
            tec_client.disconnect()
            tec_client = None
            self.connected.emit(False)


class ClientWatcher(QThread):
    fan_update = pyqtSignal(object)
    pwm_update = pyqtSignal(object)
    report_update = pyqtSignal(object)
    pid_update = pyqtSignal(object)

    def __init__(self, parent, update_s):
        self.update_s = update_s
        self.running = True
        super().__init__(parent)

    def run(self):
        while self.running:
            thread_pool.start(ClientTask(lambda: self.update_params()))
            self.msleep(int(self.update_s * 1000))

    def update_params(self):
        self.fan_update.emit(tec_client.fan())

    @pyqtSlot()
    def stop_watching(self):
        self.running = False
        deadline = QDeadlineTimer()
        deadline.setDeadline(100)
        self.wait(deadline)
        self.terminate()

    @pyqtSlot()
    def set_update_s(self):
        self.update_s = ui.report_refresh_spin.value()


class ClientTask(QRunnable):
    def __init__(self, func, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        super().__init__()

    def run(self):
        try:
            self.func(*self.args, **self.kwargs)
        except (TimeoutError, OSError):
            logging.warning("Client connection error, disconnecting", exc_info=True)
            if connection_watcher:
                thread_pool.clear()  # clearing all next requests
                connection_watcher.client_disconnected()


def connected(result):
    global client_watcher, connection_watcher
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
    elif client_watcher is None:
        client_watcher = ClientWatcher(ui.main_widget, ui.report_refresh_spin.value())
        client_watcher.fan_update.connect(fan_update)
        ui.report_apply_btn.clicked.connect(client_watcher.set_update_s)
        app.aboutToQuit.connect(client_watcher.stop_watching)
        client_watcher.start()


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


def fan_set():
    global tec_client
    if tec_client is None or ui.fan_auto_box.isChecked():
        return
    thread_pool.start(ClientTask(lambda: tec_client.set_param("fan", ui.fan_power_slider.value())))


def fan_auto_set(enabled):
    global tec_client
    if tec_client is None:
        return
    ui.fan_power_slider.setEnabled(not enabled)
    if enabled:
        thread_pool.start(ClientTask(lambda: tec_client.set_param("fan", "auto")))
    else:
        thread_pool.start(ClientTask(lambda: tec_client.set_param("fan", ui.fan_power_slider.value())))


def connect():
    global connection_watcher
    connection_watcher = WatchConnectTask(ui.main_widget, ui.ip_set_line.text(), ui.port_set_spin.value())
    connection_watcher.connected.connect(connected)
    connection_watcher.connecting.connect(lambda: ui.status_lbl.setText("Connecting..."))
    connection_watcher.hw_rev.connect(hw_rev)
    connection_watcher.fan_update.connect(fan_update)
    connection_watcher.start()
    app.aboutToQuit.connect(connection_watcher.terminate)


def main():
    global ui, thread_pool, app
    args = get_argparser().parse_args()
    if args.logLevel:
        logging.basicConfig(level=getattr(logging, args.logLevel))

    app = QtWidgets.QApplication(sys.argv)
    main_window = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(main_window)
    # ui = uic.loadUi('tec_qt.ui', main_window)

    thread_pool = QThreadPool(parent=ui.main_widget)
    thread_pool.setMaxThreadCount(1)  # avoid concurrent requests

    ui.connect_btn.clicked.connect(lambda _checked: connect())
    ui.fan_power_slider.valueChanged.connect(fan_set)
    ui.fan_auto_box.stateChanged.connect(fan_auto_set)

    if args.connect:
        if args.IP:
            ui.ip_set_line.setText(args.IP)
        if args.PORT:
            ui.port_set_spin.setValue(int(args.PORT))
        ui.connect_btn.click()

    main_window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
