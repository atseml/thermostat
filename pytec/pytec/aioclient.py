import asyncio
import json
import logging

class CommandError(Exception):
    pass

class StoppedConnecting(Exception):
    pass

class Client:
    def __init__(self):
        self._reader = None
        self._writer = None
        self._connecting_task = None
        self._command_lock = asyncio.Lock()
        self._report_mode_on = False
        self.timeout = None

    async def start_session(self, host='192.168.1.26', port=23, timeout=None):
        """Start session to Thermostat at specified host and port.
        Throws StoppedConnecting if disconnect was called while connecting.
        Throws asyncio.TimeoutError if timeout was exceeded.

        Example::
            client = Client()
            try:
                await client.start_session()
            except StoppedConnecting:
                print("Stopped connecting")
        """
        self._connecting_task = asyncio.create_task(
            asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        )
        self.timeout = timeout
        try:
            self._reader, self._writer = await self._connecting_task
        except asyncio.CancelledError:
            raise StoppedConnecting
        finally:
            self._connecting_task = None

        await self._check_zero_limits()

    def connecting(self):
        """Returns True if client is connecting"""
        return self._connecting_task is not None

    def connected(self):
        """Returns True if client is connected"""
        return self._writer is not None

    async def end_session(self):
        """End session to Thermostat if connected, cancel connection if connecting"""
        if self._connecting_task is not None:
            self._connecting_task.cancel()

        if self._writer is None:
            return

        # Reader needn't be closed
        self._writer.close()
        await self._writer.wait_closed()
        self._reader = None
        self._writer = None

    async def _check_zero_limits(self):
        pwm_report = await self.get_pwm()
        for pwm_channel in pwm_report:
            for limit in ["max_i_neg", "max_i_pos", "max_v"]:
                if pwm_channel[limit]["value"] == 0.0:
                    logging.warning("`{}` limit is set to zero on channel {}".format(limit, pwm_channel["channel"]))

    async def _read_line(self):
        # read 1 line
        chunk = await asyncio.wait_for(self._reader.readline(), self.timeout) # Only wait for response until timeout
        return chunk.decode('utf-8', errors='ignore')

    async def _read_write(self, command):
        self._writer.write(((" ".join(command)).strip() + "\n").encode('utf-8'))
        await self._writer.drain()

        return await self._read_line()

    async def _command(self, *command):
        async with self._command_lock:
            # protect the read-write process from being cancelled midway
            line = await asyncio.shield(self._read_write(command))

        response = json.loads(line)
        logging.debug(f"{command}: {response}")
        if "error" in response:
            raise CommandError(response["error"])
        return response

    async def _get_conf(self, topic):
        result = [None, None]
        for item in await self._command(topic):
            result[int(item["channel"])] = item
        return result

    async def get_pwm(self):
        """Retrieve PWM limits for the TEC

        Example::
            [{'channel': 0,
              'center': 'vref',
              'i_set': {'max': 2.9802790335151985, 'value': -0.02002179650216762},
              'max_i_neg': {'max': 3.0, 'value': 3.0},
              'max_v': {'max': 5.988, 'value': 5.988},
              'max_i_pos': {'max': 3.0, 'value': 3.0}},
             {'channel': 1,
              'center': 'vref',
              'i_set': {'max': 2.9802790335151985, 'value': -0.02002179650216762},
              'max_i_neg': {'max': 3.0, 'value': 3.0},
              'max_v': {'max': 5.988, 'value': 5.988},
              'max_i_pos': {'max': 3.0, 'value': 3.0}}
            ]
        """
        return await self._get_conf("pwm")

    async def get_pid(self):
        """Retrieve PID control state

        Example::
            [{'channel': 0,
              'parameters': {
                  'kp': 10.0,
                  'ki': 0.02,
                  'kd': 0.0,
                  'output_min': 0.0,
                  'output_max': 3.0},
              'target': 37.0},
             {'channel': 1,
              'parameters': {
                  'kp': 10.0,
                  'ki': 0.02,
                  'kd': 0.0,
                  'output_min': 0.0,
                  'output_max': 3.0},
              'target': 36.5}]
        """
        return await self._get_conf("pid")

    async def get_steinhart_hart(self):
        """Retrieve Steinhart-Hart parameters for resistance to temperature conversion

        Example::
            [{'params': {'b': 3800.0, 'r0': 10000.0, 't0': 298.15}, 'channel': 0},
             {'params': {'b': 3800.0, 'r0': 10000.0, 't0': 298.15}, 'channel': 1}]
        """
        return await self._get_conf("s-h")

    async def get_postfilter(self):
        """Retrieve DAC postfilter configuration

        Example::
            [{'rate': None, 'channel': 0},
             {'rate': 21.25, 'channel': 1}]
        """
        return await self._get_conf("postfilter")

    async def get_fan(self):
        """Get Thermostat current fan settings"""
        return await self._command("fan")

    async def report(self):
        """Obtain one-time report on measurement values"""
        return await self._command("report")

    async def report_mode(self):
        """Start reporting measurement values

        Example of yielded data::
            {'channel': 0,
             'time': 2302524,
             'adc': 0.6199188965423515,
             'sens': 6138.519310282602,
             'temperature': 36.87032392655527,
             'pid_engaged': True,
             'i_set': 2.0635816680889123,
             'vref': 1.494,
             'dac_value': 2.527790834044456,
             'dac_feedback': 2.523,
             'i_tec': 2.331,
             'tec_i': 2.0925,
             'tec_u_meas': 2.5340000000000003,
             'pid_output': 2.067581958092247}
        """
        await self._command("report mode", "on")
        self._report_mode_on = True

        while self._report_mode_on:
            async with self._command_lock:
                line = await self._read_line()
            if not line:
                break
            try:
                yield json.loads(line)
            except json.decoder.JSONDecodeError:
                pass

        await self._command("report mode", "off")

    def stop_report_mode(self):
        self._report_mode_on = False

    async def set_param(self, topic, channel, field="", value=""):
        """Set configuration parameters

        Examples::
            await tec.set_param("pwm", 0, "max_v", 2.0)
            await tec.set_param("pid", 1, "output_max", 2.5)
            await tec.set_param("s-h", 0, "t0", 20.0)
            await tec.set_param("center", 0, "vref")
            await tec.set_param("postfilter", 1, 21)

        See the firmware's README.md for a full list.
        """
        if type(value) is float:
            value = "{:f}".format(value)
        if type(value) is not str:
            value = str(value)
        await self._command(topic, str(channel), field, value)

    async def set_fan(self, power="auto"):
        """Set fan power"""
        await self._command("fan", str(power))

    async def set_fcurve(self, a=1.0, b=0.0, c=0.0):
        """Set fan curve"""
        await self._command("fcurve", str(a), str(b), str(c))

    async def power_up(self, channel, target):
        """Start closed-loop mode"""
        await self.set_param("pid", channel, "target", value=target)
        await self.set_param("pwm", channel, "pid")

    async def save_config(self, channel=""):
        """Save current configuration to EEPROM"""
        await self._command("save", str(channel))

    async def load_config(self, channel=""):
        """Load current configuration from EEPROM"""
        await self._command("load", str(channel))
        if channel == "":
            await self._read_line() # Read the extra {}

    async def hw_rev(self):
        """Get Thermostat hardware revision"""
        return await self._command("hwrev")

    async def reset(self):
        """Reset the Thermostat
        
        The client is disconnected as the TCP session is terminated.
        """
        async with self._command_lock:
            self._writer.write("reset\n".encode('utf-8'))
            await self._writer.drain()

        await self.end_session()

    async def dfu(self):
        """Put the Thermostat in DFU update mode
        
        The client is disconnected as the Thermostat stops responding to
        TCP commands in DFU update mode. The only way to exit it is by
        power-cycling.
        """
        async with self._command_lock:
            self._writer.write("dfu\n".encode('utf-8'))
            await self._writer.drain()

        await self.end_session()

    async def ipv4(self):
        """Get the IPv4 settings of the Thermostat"""
        return await self._command('ipv4')
