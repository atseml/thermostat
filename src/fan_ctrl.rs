use serde::Serialize;
use stm32f4xx_hal::{
    pwm::{self, PwmChannels},
    pac::TIM8,
    gpio::{
        Floating, Input, ExtiPin,
        gpioc::PC8, Edge,
    },
    stm32::EXTI,
    syscfg::{SysCfg},
};
use smoltcp::time::Instant;

use crate::{
    pins::HWRevPins,
    channels::{Channels, JsonBuffer},
    timer
};

pub type FanPin = PwmChannels<TIM8, pwm::C4>;
pub type TachoPin = PC8<Input<Floating>>;

// as stated in the schematics
const MAX_TEC_I: f64 = 3.0;

const MAX_USER_FAN_PWM: f64 = 100.0;
const MIN_USER_FAN_PWM: f64 = 1.0;
const MAX_FAN_PWM: f64 = 1.0;
// below this value, motor pulse signal is too weak to be registered by tachometer
const MIN_FAN_PWM: f64 = 0.05;

const TACHO_MEASURE_MS: i64 = 2500;
// by default up to 2 cycles are skipped on changes in PWM output,
// and the halt threshold will help detect the failure during these skipped cycles
const TACHO_HALT_THRESHOLD: u32 = 250;
const TACHO_SKIP_CYCLES: u8 = 2;

const DEFAULT_K_A: f64 = 1.0;
const DEFAULT_K_B: f64 = 0.0;
const DEFAULT_K_C: f64 = 0.0;

// This regression is from 6% to 25% lower than values registered in the experiments.
// Actual values would be better estimated by logarithmic regression, but that would require more
// runtime computation, and wouldn't give significant correlation difference
// (0.996 for log and 0.966 for quadratic regression).
const TACHO_REGRESSION_A: f64 = -0.04135128436;
const TACHO_REGRESSION_B: f64 = 6.23015531;
const TACHO_REGRESSION_C: f64 = 403.6833577;


#[derive(Serialize, Copy, Clone)]
pub struct HWRev {
    pub major: u8,
    pub minor: u8,
}

#[derive(Serialize, Clone, Copy, PartialEq)]
pub enum FanStatus {
    OK,
    NotAvailable,
    TooSlow,
    Halted
}

struct TachoCtrl {
    tacho: TachoPin,
    tacho_cnt: u32,
    tacho_value: Option<u32>,
    prev_epoch: i64,
}

pub struct FanCtrl {
    fan: FanPin,
    tacho: TachoCtrl,
    fan_auto: bool,
    available: bool,
    k_a: f64,
    k_b: f64,
    k_c: f64,
    pub channels: Channels,
    last_status: FanStatus,
    skip_cycles: u8,
}

impl FanCtrl {
    pub fn new(mut fan: FanPin, tacho: TachoPin, channels: Channels, exti: &mut EXTI, syscfg: &mut SysCfg) -> Self {
        let available = channels.hwrev.fan_available();

        let mut tacho_ctrl = TachoCtrl::new(tacho);
        if available {
            fan.set_duty(0);
            fan.enable();
            tacho_ctrl.init(exti, syscfg);
        }

        FanCtrl {
            fan,
            tacho: tacho_ctrl,
            available,
            fan_auto: true,
            k_a: DEFAULT_K_A,
            k_b: DEFAULT_K_B,
            k_c: DEFAULT_K_C,
            channels,
            last_status: if available { FanStatus::OK } else { FanStatus::NotAvailable },
            skip_cycles: 0
        }
    }

    pub fn cycle(&mut self) -> Result<(), FanStatus> {
        if self.available {
            if self.tacho.cycle() {
                self.skip_cycles >>= 1;
            }
        }
        self.adjust_speed();
        let diagnose = self.diagnose();
        if (self.skip_cycles == 0 || diagnose == FanStatus::Halted) && diagnose != self.last_status {
            self.last_status = diagnose;
            Err(diagnose)
        } else {
            Ok(())
        }
    }

    pub fn summary(&mut self) -> Result<JsonBuffer, serde_json_core::ser::Error> {
        if self.available {
            let summary = FanSummary {
                fan_pwm: self.get_pwm(),
                tacho: self.tacho.get(),
                abs_max_tec_i: self.channels.current_abs_max_tec_i(),
                auto_mode: self.fan_auto,
                status: self.diagnose(),
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
        self.set_auto_mode(true);
        self.set_curve(DEFAULT_K_A, DEFAULT_K_B, DEFAULT_K_C);
    }

    pub fn set_pwm(&mut self, fan_pwm: u32) -> f64 {
        let fan_pwm = fan_pwm.min(MAX_USER_FAN_PWM as u32).max(MIN_USER_FAN_PWM as u32);
        self.skip_cycles = if (self.tacho.get() as f64) <= Self::threshold_for_pwm(fan_pwm as f64) {
            TACHO_SKIP_CYCLES
        } else { self.skip_cycles };
        let duty = Self::scale_number(fan_pwm as f64, MIN_FAN_PWM, MAX_FAN_PWM, MIN_USER_FAN_PWM, MAX_USER_FAN_PWM);
        let max = self.fan.get_max_duty();
        let value = ((duty * (max as f64)) as u16).min(max);
        self.fan.set_duty(value);
        value as f64 / (max as f64)
    }

    #[inline]
    fn threshold_for_pwm(fan_pwm: f64) -> f64 {
        (TACHO_REGRESSION_A * fan_pwm + TACHO_REGRESSION_B) * fan_pwm + TACHO_REGRESSION_C
    }

    #[inline]
    fn scale_number(unscaled: f64, to_min: f64, to_max: f64, from_min: f64, from_max: f64) -> f64 {
        (to_max - to_min) * (unscaled - from_min) / (from_max - from_min) + to_min
    }

    fn diagnose(&mut self) -> FanStatus {
        if !self.available {
            return FanStatus::NotAvailable;
        }
        let threshold = Self::threshold_for_pwm(self.get_pwm() as f64) as u32;
        let tacho = self.tacho.get();
        if tacho >= threshold {
            FanStatus::OK
        } else if tacho >= TACHO_HALT_THRESHOLD {
            FanStatus::TooSlow
        } else {
            FanStatus::Halted
        }
    }

    fn get_pwm(&self) -> u32 {
        let duty = self.fan.get_duty();
        let max = self.fan.get_max_duty();
        (Self::scale_number(duty as f64 / (max as f64), MIN_USER_FAN_PWM, MAX_USER_FAN_PWM, MIN_FAN_PWM, MAX_FAN_PWM) + 0.5) as u32
    }
}

impl TachoCtrl {
    fn new(tacho: TachoPin) -> Self {
        TachoCtrl {
            tacho,
            tacho_cnt: 0,
            tacho_value: None,
            prev_epoch: 0,
        }
    }

    fn init(&mut self, exti: &mut EXTI, syscfg: &mut SysCfg) {
        // These lines do not cause NVIC to run the ISR,
        // since the interrupt is masked in the cortex_m::peripheral::NVIC.
        // Also using interrupt-related workaround is the best
        // option for the current version of stm32f4xx-hal,
        // since tying the IC's PC8 with the PWM's PC9 to the same TIM8 is not supported.
        // The possible solution would be to update the library to >=v0.14.*,
        // and use its Timer's counter functionality.
        self.tacho.make_interrupt_source(syscfg);
        self.tacho.trigger_on_edge(exti, Edge::Rising);
        self.tacho.enable_interrupt(exti);
    }

    // returns whether the epoch elapsed
    fn cycle(&mut self) -> bool {
        let tacho_input = self.tacho.check_interrupt();
        if tacho_input {
            self.tacho.clear_interrupt_pending_bit();
            self.tacho_cnt += 1;
        }

        let instant = Instant::from_millis(i64::from(timer::now()));
        if instant.millis - self.prev_epoch >= TACHO_MEASURE_MS {
            self.tacho_value = Some(self.tacho_cnt);
            self.tacho_cnt = 0;
            self.prev_epoch = instant.millis;
            true
        } else {
            false
        }
    }

    fn get(&self) -> u32 {
        self.tacho_value.unwrap_or(u32::MAX)
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
    tacho: u32,
    abs_max_tec_i: f64,
    auto_mode: bool,
    status: FanStatus,
    k_a: f64,
    k_b: f64,
    k_c: f64,
}

impl FanStatus {
    pub fn fmt_u8(&self) -> &'static [u8] {
        match *self {
            FanStatus::OK => "Fan is OK".as_bytes(),
            FanStatus::NotAvailable => "Fan is not available".as_bytes(),
            FanStatus::TooSlow => "Fan is too slow".as_bytes(),
            FanStatus::Halted => "Fan is halted".as_bytes(),
        }
    }
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
