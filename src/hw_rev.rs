use serde::Serialize;

use crate::{
    pins::HWRevPins,
    command_handler::JsonBuffer
};

#[derive(Serialize, Copy, Clone)]
pub struct HWRev {
    pub major: u8,
    pub minor: u8,
}


impl HWRev {
    pub fn detect_hw_rev(hwrev_pins: &HWRevPins) -> Self {
        let (h0, h1, h2, h3) = (hwrev_pins.hwrev0.is_high(), hwrev_pins.hwrev1.is_high(),
                                hwrev_pins.hwrev2.is_high(), hwrev_pins.hwrev3.is_high());
        match (h0, h1, h2, h3) {
            (true, true, true, false) => HWRev { major: 1, minor: 0 },
            (true, false, false, false) => HWRev { major: 2, minor: 0 },
            (false, true, false, false) => HWRev { major: 2, minor: 2 },
            (_, _, _, _) => HWRev { major: 0, minor: 0 }
        }
    }

    pub fn fan_available(&self) -> bool {
        self.major == 2 && self.minor == 2
    }

    pub fn fan_default_auto(&self) -> bool {
        // see https://github.com/sinara-hw/Thermostat/issues/115 and
        // https://git.m-labs.hk/M-Labs/thermostat/issues/69#issuecomment-6464 for explanation
        self.fan_available() && self.minor != 2
    }

    pub fn summary(&self) -> Result<JsonBuffer, serde_json_core::ser::Error> {
        serde_json_core::to_vec(&self)

    }
}