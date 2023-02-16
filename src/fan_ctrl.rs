use num_traits::Float;
use serde::Serialize;
use stm32f4xx_hal::{
    pwm::{self, PwmChannels},
    pac::TIM8,
};

use crate::{
    hw_rev::HWRev,
    command_handler::JsonBuffer,
};

pub type FanPin = PwmChannels<TIM8, pwm::C4>;

// as stated in the schematics
const MAX_TEC_I: f32 = 3.0;

const MAX_USER_FAN_PWM: f32 = 100.0;
const MIN_USER_FAN_PWM: f32 = 1.0;
const MAX_FAN_PWM: f32 = 1.0;
// below this value motor's autostart feature may fail
const MIN_FAN_PWM: f32 = 0.04;

const DEFAULT_K_A: f32 = 1.0;
const DEFAULT_K_B: f32 = 0.0;
const DEFAULT_K_C: f32 = 0.0;

pub struct FanCtrl {
    fan: FanPin,
    fan_auto: bool,
    available: bool,
    default_auto: bool,
    pwm_enabled: bool,
    k_a: f32,
    k_b: f32,
    k_c: f32,
    abs_max_tec_i: f32,
}

impl FanCtrl {
    pub fn new(fan: FanPin, hwrev: HWRev) -> Self {
        let available = hwrev.fan_available();
        let default_auto = hwrev.fan_default_auto();

        let mut fan_ctrl = FanCtrl {
            fan,
            available,
            // do not enable auto mode by default,
            // but allow to turn it on on user's own risk
            default_auto,
            fan_auto: default_auto,
            pwm_enabled: false,
            k_a: DEFAULT_K_A,
            k_b: DEFAULT_K_B,
            k_c: DEFAULT_K_C,
            abs_max_tec_i: 0f32,
        };
        if fan_ctrl.fan_auto {
            fan_ctrl.enable_pwm();
        }
        fan_ctrl
    }

    pub fn cycle(&mut self, abs_max_tec_i: f32) {
        self.abs_max_tec_i = abs_max_tec_i;
        self.adjust_speed();
    }

    pub fn summary(&mut self) -> Result<JsonBuffer, serde_json_core::ser::Error> {
        if self.available {
            let summary = FanSummary {
                fan_pwm: self.get_pwm(),
                abs_max_tec_i: self.abs_max_tec_i,
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
            let scaled_current = self.abs_max_tec_i / MAX_TEC_I;
            // do not limit upper bound, as it will be limited in the set_pwm()
            let pwm = (MAX_USER_FAN_PWM * (scaled_current * (scaled_current * self.k_a + self.k_b) + self.k_c)) as u32;
            self.set_pwm(pwm);
        }
    }

    pub fn set_auto_mode(&mut self, fan_auto: bool) {
        self.fan_auto = fan_auto;
    }

    pub fn set_curve(&mut self, k_a: f32, k_b: f32, k_c: f32) {
        self.k_a = k_a;
        self.k_b = k_b;
        self.k_c = k_c;
    }

    pub fn restore_defaults(&mut self) {
        self.set_curve(DEFAULT_K_A, DEFAULT_K_B, DEFAULT_K_C);
    }

    pub fn set_pwm(&mut self, fan_pwm: u32) -> f32 {
        if !self.pwm_enabled {
            self.enable_pwm()
        }
        let fan_pwm = fan_pwm.min(MAX_USER_FAN_PWM as u32).max(MIN_USER_FAN_PWM as u32);
        let duty = Self::scale_number(fan_pwm as f32, MIN_FAN_PWM, MAX_FAN_PWM, MIN_USER_FAN_PWM, MAX_USER_FAN_PWM);
        let max = self.fan.get_max_duty();
        let value = ((duty * (max as f32)) as u16).min(max);
        self.fan.set_duty(value);
        value as f32 / (max as f32)
    }

    pub fn is_default_auto(&self) -> bool {
        self.default_auto
    }

    fn scale_number(unscaled: f32, to_min: f32, to_max: f32, from_min: f32, from_max: f32) -> f32 {
        (to_max - to_min) * (unscaled - from_min) / (from_max - from_min) + to_min
    }

    fn get_pwm(&self) -> u32 {
        let duty = self.fan.get_duty();
        let max = self.fan.get_max_duty();
        Self::scale_number(duty as f32 / (max as f32), MIN_USER_FAN_PWM, MAX_USER_FAN_PWM, MIN_FAN_PWM, MAX_FAN_PWM).round() as u32
    }

    fn enable_pwm(&mut self) {
        if self.available {
            self.fan.set_duty(0);
            self.fan.enable();
            self.pwm_enabled = true;
        }
    }
}

#[derive(Serialize)]
pub struct FanSummary {
    fan_pwm: u32,
    abs_max_tec_i: f32,
    auto_mode: bool,
    k_a: f32,
    k_b: f32,
    k_c: f32,
}
