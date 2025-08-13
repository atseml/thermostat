from functools import partial
from PyQt6.QtCore import pyqtSignal, QObject, QSignalBlocker, pyqtSlot
import pyqtgraph.parametertree.parameterTypes as pTypes
from pyqtgraph.parametertree import (
    Parameter,
    registerParameterType,
)
from qasync import asyncSlot
from pythermostat.autotune import PIDAutotuneState


class CtrlPanel(QObject):
    
    sigQueuedChangedSetting = pyqtSignal(int)
    
    def __init__(
        self,
        thermostat,
        autotuners,
        info_box,
        trees_ui,
        param_tree,
        parent=None,
    ):
        super().__init__(parent)

        self.thermostat = thermostat
        self.autotuners = autotuners
        self.info_box = info_box
        self.trees_ui = trees_ui
        self.NUM_CHANNELS = len(trees_ui)
        self._queued_changes = {}
        self._settings_visual_update = set()

        self.THERMOSTAT_PARAMETERS = [param_tree for i in range(self.NUM_CHANNELS)]

        self.params = [
            Parameter.create(
                name=f"Thermostat Channel {ch} Parameters",
                type="group",
                value=ch,
                children=self.THERMOSTAT_PARAMETERS[ch],
            )
            for ch in range(self.NUM_CHANNELS)
        ]

        for i, param in enumerate(self.params):
            param.channel = i

        for i, tree in enumerate(self.trees_ui):
            tree.setHeaderHidden(True)
            tree.setParameters(self.params[i], showTop=False)
            self.params[i].setValue = self._setValue
            self.params[i].sigTreeStateChanged.connect(self._queue_changes)

            self.params[i].child("save").sigActivated.connect(
                partial(self.save_settings, i)
            )
            self.params[i].child("load").sigActivated.connect(
                partial(self.load_settings, i)
            )
            self.params[i].child("pid", "pid_autotune", "run_pid").sigActivated.connect(
                partial(self.pid_auto_tune_request, i)
            )

            def _ctrlTempMeth(param, control_method="constant_current"):
                name = {"constant_current": "i_set", "temperature_pid":"target"}[control_method]
                for item in param.children():
                    item.show(item.opts["name"]==name)
            
            self.params[i].child("output", "control_method").sigValueChanged.connect(_ctrlTempMeth)
            _ctrlTempMeth(self.params[i].child("output", "control_method"))

        self.thermostat.pid_update.connect(self.update_pid)
        self.thermostat.report_update.connect(self.update_report)
        self.thermostat.thermistor_update.connect(self.update_thermistor)
        self.thermostat.output_update.connect(self.update_output)
        self.thermostat.postfilter_update.connect(self.update_postfilter)
        self.autotuners.autotune_state_changed.connect(self.update_pid_autotune)

    def _setValue(self, value, blockSignal=None):
        """
        Implement 'lock' mechanism for Parameter Type

        Modified from the source
        """
        try:
            if blockSignal is not None:
                self.sigValueChanged.disconnect(blockSignal)
            value = self._interpretValue(value)
            if fn.eq(self.opts["value"], value):
                return value

            if "lock" in self.opts.keys():
                if self.opts["lock"]:
                    return value
            self.opts["value"] = value
            self.sigValueChanged.emit(
                self, value
            )  # value might change after signal is received by tree item
        finally:
            if blockSignal is not None:
                self.sigValueChanged.connect(blockSignal)

        return self.opts["value"]

    @property
    def queued_changes(self):
        return self._queued_changes

    def change_params_title(self, channel, path, title):
        self.params[channel].child(*path).setOpts(title=title)

    @asyncSlot(object, object)
    async def _queue_changes(self, param, changes):
        """Translates parameter tree changes into thermostat set_param calls"""
        ch = param.channel

        for inner_param, change_type, data in changes: 
            if change_type != "value":
                continue
            
            thermostat_param = inner_param.opts["thermostat:set_param"]
            if inner_param.opts["type"] in ["list"]:
                match inner_param.name(), data:
                    case "rate", None:
                        thermostat_param = thermostat_param.copy()
                        thermostat_param["field"] = "off"
                        data = ""
                    case "control_method", "constant_current":
                        thermostat_param = thermostat_param.copy()
                        thermostat_param["field"] = "i_set"
                        data = inner_param.child("i_set").value()
                    case "control_method", "temperature_pid":
                        data = ""

            if not inner_param.opts.get("excludeQueue", False):
                self._queued_changes[inner_param] = (ch, data, thermostat_param) 
                self.sigQueuedChangedSetting.emit(ch)
                continue

            await self.apply_setting(inner_param, ch, data, thermostat_param)

    async def apply_setting(self, param, channel, data, thermostat_param):
        param.setOpts(lock=True)
        await self.thermostat.set_param(channel=channel, value=data, **thermostat_param)
        param.setOpts(lock=False)

    def flush_queued_settings(self):
        self._queued_changes.clear()
    
    def _is_in_queued_changes(self, setting, ch):
        for param, cont in self._queued_changes.items():
            _ch,_data,_thermo_param = cont
            if ch == _ch and setting == param.opts["name"]:
                return True
        return False

    def _handle_queued_settings(self, ch, data, path):
        name = path[-1]
        setting_param = self.params[ch].child(*path)
        is_queued_setting = self._is_in_queued_changes(name, ch)
        is_in_setting_visual_update = (name, ch) in self._settings_visual_update
        match is_queued_setting, is_in_setting_visual_update:
            case True, False:
                self._settings_visual_update.add( (name, ch) )
                setting_param.setOpts(title=setting_param.opts["title"] + " (*)")
                for item in setting_param.items:
                    font = item.font(0); font.setBold(True); font.setUnderline(True)
                    item.setFont(0, font)
            case True, _:
                for item in setting_param.items:
                    item.setToolTip(1, f"Current value: {data}")
            case False, True:
                setting_param.setValue(data)
                setting_param.setOpts(title=(setting_param.opts["title"])[0:-3])
                for item in setting_param.items:
                    font = item.font(0); font.setBold(False); font.setUnderline(False)
                    item.setFont(0, font)
                self._settings_visual_update.discard( (name, ch) )
            case False, False:
                setting_param.setValue(data)
                for item in setting_param.items:
                    item.setToolTip(1, f"Current value: {data}")

    @pyqtSlot(list)
    def update_pid(self, pid_settings):
        for settings in pid_settings:
            channel = settings["channel"]
            with QSignalBlocker(self.params[channel]):
                for name in ["kp", "ki", "kd"]:
                    self._handle_queued_settings(channel, settings["parameters"][name], ("pid", name))
                self._handle_queued_settings(channel, settings["parameters"]["output_min"]*1000, ("pid", "pid_output_clamping", "output_min"))
                self._handle_queued_settings(channel, settings["parameters"]["output_max"]*1000, ("pid", "pid_output_clamping", "output_min"))
                self._handle_queued_settings(channel, settings["target"], ("output", "control_method", "target"))

    @pyqtSlot(list)
    def update_report(self, report_data):
        for settings in report_data:
            channel = settings["channel"]
            with QSignalBlocker(self.params[channel]):
                self.params[channel].child("output", "control_method").setValue(
                    "temperature_pid" if settings["pid_engaged"] else "constant_current"
                )
                self._handle_queued_settings(channel, settings["i_set"]*1000, ("output", "control_method", "i_set"))
                if settings["temperature"] is not None:
                    self.params[channel].child("readings", "temperature").setValue(
                        settings["temperature"]
                    )
                    if settings["tec_i"] is not None:
                        self.params[channel].child("readings", "tec_i").setValue(
                            settings["tec_i"] * 1000
                        )

    @pyqtSlot(list)
    def update_thermistor(self, sh_data):
        for sh_param in sh_data:
            channel = sh_param["channel"]
            with QSignalBlocker(self.params[channel]):
                self._handle_queued_settings(channel, sh_param["params"]["t0"]-273.15, ("thermistor", "t0"))
                self._handle_queued_settings(channel, sh_param["params"]["r0"], ("thermistor", "r0"))
                self._handle_queued_settings(channel, sh_param["params"]["b"], ("thermistor", "b"))

    @pyqtSlot(list)
    def update_output(self, output_data):
        for output_params in output_data:
            channel = output_params["channel"]
            with QSignalBlocker(self.params[channel]):
                self._handle_queued_settings(channel, output_params["max_v"], ("output", "limits", "max_v"))
                self._handle_queued_settings(channel, output_params["max_i_pos"]*1000, ("output", "limits", "max_i_pos"))
                self._handle_queued_settings(channel, output_params["max_i_neg"]*1000, ("output", "limits", "max_i_neg"))

    @pyqtSlot(list)
    def update_postfilter(self, postfilter_data):
        for postfilter_params in postfilter_data:
            channel = postfilter_params["channel"]
            with QSignalBlocker(self.params[channel]):
                self._handle_queued_settings(channel, postfilter_params["rate"], ("thermistor", "rate"))

    def update_pid_autotune(self, ch, state):
        match state:
            case PIDAutotuneState.OFF:
                self.change_params_title(ch, ("pid", "pid_autotune", "run_pid"), "Run")
            case (
                PIDAutotuneState.READY
                | PIDAutotuneState.RELAY_STEP_UP
                | PIDAutotuneState.RELAY_STEP_DOWN
            ):
                self.change_params_title(ch, ("pid", "pid_autotune", "run_pid"), "Stop")
            case PIDAutotuneState.SUCCEEDED:
                self.info_box.display_info_box(
                    "PID Autotune Success",
                    f"Channel {ch} PID Settings has been loaded to Thermostat. Regulating temperature.",
                )
            case PIDAutotuneState.FAILED:
                self.info_box.display_info_box(
                    "PID Autotune Failed",
                    f"Channel {ch} PID Autotune has failed.",
                )

    @asyncSlot(int)
    async def load_settings(self, ch):
        await self.thermostat.load_cfg(ch)

        self.info_box.display_info_box(
            f"Channel {ch} settings loaded",
            f"Channel {ch} settings has been loaded from flash.",
        )

    @asyncSlot(int)
    async def save_settings(self, ch):
        await self.thermostat.save_cfg(ch)

        self.info_box.display_info_box(
            f"Channel {ch} settings saved",
            f"Channel {ch} settings has been saved to flash.\n"
            "It will be loaded on Thermostat reset, or when settings are explicitly loaded.",
        )

    @asyncSlot()
    async def pid_auto_tune_request(self, ch=0):
        match self.autotuners.get_state(ch):
            case PIDAutotuneState.OFF | PIDAutotuneState.FAILED:
                self.autotuners.load_params_and_set_ready(ch)

            case (
                PIDAutotuneState.READY
                | PIDAutotuneState.RELAY_STEP_UP
                | PIDAutotuneState.RELAY_STEP_DOWN
            ):
                await self.autotuners.stop_pid_from_running(ch)
