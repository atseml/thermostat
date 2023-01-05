use serde::Serialize;
use stm32f4xx_hal::{
    pwm::{self, PwmChannels},
    pac::TIM8,
};

use crate::{
    pins::HWRevPins,
    channels::{Channels, JsonBuffer},
};

pub type FanPin = PwmChannels<TIM8, pwm::C4>;

// as stated in the schematics
const MAX_TEC_I: f64 = 3.0;

const MAX_USER_FAN_PWM: f64 = 100.0;
const MIN_USER_FAN_PWM: f64 = 1.0;
const MAX_FAN_PWM: f64 = 1.0;
// below this value, motor pulse signal is too weak
const MIN_FAN_PWM: f64 = 0.05;

const DEFAULT_K_A: f64 = 1.0;
const DEFAULT_K_B: f64 = 0.0;
const DEFAULT_K_C: f64 = 0.0;


#[derive(Serialize, Copy, Clone)]
pub struct HWRev {
    pub major: u8,
    pub minor: u8,
}

pub struct FanCtrl {
    fan: FanPin,
    fan_auto: bool,
    available: bool,
    k_a: f64,
    k_b: f64,
    k_c: f64,
    pub channels: Channels,
}

impl FanCtrl {
    pub fn new(mut fan: FanPin, channels: Channels) -> Self {
        let available = channels.hwrev.fan_available();

        if available {
            fan.set_duty(0);
            fan.enable();
        }

        FanCtrl {
            fan,
            available,
            fan_auto: true,
            k_a: DEFAULT_K_A,
            k_b: DEFAULT_K_B,
            k_c: DEFAULT_K_C,
            channels,
        }
    }

    pub fn cycle(&mut self) {
        self.adjust_speed();
    }

    pub fn summary(&mut self) -> Result<JsonBuffer, serde_json_core::ser::Error> {
        if self.available {
            let summary = FanSummary {
                fan_pwm: self.get_pwm(),
                abs_max_tec_i: self.channels.current_abs_max_tec_i(),
                auto_mode: self.fan_auto,
                k_a: self.k_a,
                k_b: self.k_b,
                k_c: self.k_c,
            };
            serde_json_core::to_vec(&summary)
        } else {
            let summary: Option<()> = None;
            serde_json_core::to_vec(&summary)
        }
    }

    pub fn adjust_speed(&mut self) {
        if self.fan_auto && self.available {
            let scaled_current = self.channels.current_abs_max_tec_i() / MAX_TEC_I;
            // do not limit upper bound, as it will be limited in the set_pwm()
            let pwm = (MAX_USER_FAN_PWM * (scaled_current * (scaled_current * self.k_a + self.k_b) + self.k_c)) as u32;
            self.set_pwm(pwm);
        }
    }

    #[inline]
    pub fn set_auto_mode(&mut self, fan_auto: bool) {
        self.fan_auto = fan_auto;
    }

    #[inline]
    pub fn set_curve(&mut self, k_a: f64, k_b: f64, k_c: f64) {
        self.k_a = k_a;
        self.k_b = k_b;
        self.k_c = k_c;
    }

    #[inline]
    pub fn restore_defaults(&mut self) {
        self.set_curve(DEFAULT_K_A, DEFAULT_K_B, DEFAULT_K_C);
    }

    pub fn set_pwm(&mut self, fan_pwm: u32) -> f64 {
        let fan_pwm = fan_pwm.min(MAX_USER_FAN_PWM as u32).max(MIN_USER_FAN_PWM as u32);
        let duty = Self::scale_number(fan_pwm as f64, MIN_FAN_PWM, MAX_FAN_PWM, MIN_USER_FAN_PWM, MAX_USER_FAN_PWM);
        let max = self.fan.get_max_duty();
        let value = ((duty * (max as f64)) as u16).min(max);
        self.fan.set_duty(value);
        value as f64 / (max as f64)
    }

    #[inline]
    fn scale_number(unscaled: f64, to_min: f64, to_max: f64, from_min: f64, from_max: f64) -> f64 {
        (to_max - to_min) * (unscaled - from_min) / (from_max - from_min) + to_min
    }

    fn get_pwm(&self) -> u32 {
        let duty = self.fan.get_duty();
        let max = self.fan.get_max_duty();
        (Self::scale_number(duty as f64 / (max as f64), MIN_USER_FAN_PWM, MAX_USER_FAN_PWM, MIN_FAN_PWM, MAX_FAN_PWM) + 0.5) as u32
    }
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
}

#[derive(Serialize)]
pub struct FanSummary {
    fan_pwm: u32,
    abs_max_tec_i: f64,
    auto_mode: bool,
    k_a: f64,
    k_b: f64,
    k_c: f64,
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn test_scaler() {
        for x in 1..100 {
            assert_eq!((FanCtrl::scale_number(
                FanCtrl::scale_number(x as f64, MIN_FAN_PWM, MAX_FAN_PWM, MIN_USER_FAN_PWM, MAX_USER_FAN_PWM),
                                              MIN_USER_FAN_PWM, MAX_USER_FAN_PWM, MIN_FAN_PWM, MAX_FAN_PWM) + 0.5) as i32,
                       x);
        }
    }
}
