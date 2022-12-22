use core::{cmp::max_by};
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

const MAX_TEC_I: f64 = 3.0;
// as stated in the schematics
const MAX_FAN_PWM: f64 = 100.0;
const MIN_FAN_PWM: f64 = 1.0;
const TACHO_MEASURE_MS: i64 = 2500;
const DEFAULT_K_A: f64 = 1.0;
const DEFAULT_K_B: f64 = 0.0;
const DEFAULT_K_C: f64 = 0.0;

#[derive(Serialize, Copy, Clone)]
pub struct HWRev {
    pub major: u8,
    pub minor: u8,
}

struct TachoCtrl {
    tacho: TachoPin,
    tacho_cnt: u32,
    tacho_value: Option<u32>,
    prev_epoch: i64,
}

pub struct FanCtrl<'a> {
    fan: FanPin,
    tacho: TachoCtrl,
    fan_auto: bool,
    available: bool,
    k_a: f64,
    k_b: f64,
    k_c: f64,
    channels: &'a mut Channels,
}

impl<'a> FanCtrl<'a> {
    pub fn new(mut fan: FanPin, tacho: TachoPin, channels: &'a mut Channels, exti: &mut EXTI, syscfg: &mut SysCfg) -> Self {
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
        }
    }

    pub fn cycle(&mut self) {
        if self.available {
            self.tacho.cycle();
        }
        self.adjust_speed();
    }

    pub fn summary(&mut self) -> Result<JsonBuffer, serde_json_core::ser::Error> {
        if self.available {
            let summary = FanSummary {
                fan_pwm: self.get_pwm(),
                tacho: self.tacho.get(),
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
            let pwm = max_by(MAX_FAN_PWM * (scaled_current * (scaled_current * self.k_a + self.k_b) + self.k_c),
                             MIN_FAN_PWM,
                             |a, b| a.partial_cmp(b).unwrap_or(core::cmp::Ordering::Equal)) as u32;
            self.set_pwm(pwm);
        }
    }

    #[inline]
    pub fn set_auto_mode(&mut self, fan_auto: bool) {
        self.fan_auto = fan_auto;
    }

    #[inline]
    pub fn set_coefficients(&mut self, k_a: f64, k_b: f64, k_c: f64) {
        self.k_a = k_a;
        self.k_b = k_b;
        self.k_c = k_c;
    }

    #[inline]
    pub fn restore_defaults(&mut self) {
        self.set_auto_mode(true);
        self.set_coefficients(DEFAULT_K_A, DEFAULT_K_B, DEFAULT_K_C);
    }

    pub fn set_pwm(&mut self, fan_pwm: u32) -> f64 {
        let duty = fan_pwm as f64 / MAX_FAN_PWM;
        let max = self.fan.get_max_duty();
        let value = ((duty * (max as f64)) as u16).min(max);
        self.fan.set_duty(value);
        value as f64 / (max as f64)
    }

    fn get_pwm(&self) -> u32 {
        let duty = self.fan.get_duty();
        let max = self.fan.get_max_duty();
        ((duty as f64 / (max as f64)) * MAX_FAN_PWM) as u32
    }
}

impl TachoCtrl {
    pub fn new(tacho: TachoPin) -> Self {
        TachoCtrl {
            tacho,
            tacho_cnt: 0,
            tacho_value: None,
            prev_epoch: 0,
        }
    }

    pub fn init(&mut self, exti: &mut EXTI, syscfg: &mut SysCfg) {
        // These lines do not cause NVIC to run the ISR,
        // since the interrupt should be unmasked in the cortex_m::peripheral::NVIC.
        // Also using interrupt-related workaround is the best
        // option for the current version of stm32f4xx-hal,
        // since tying the IC's PC8 with the PWM's PC9 to the same TIM8 is not supported,
        // and therefore would require even more weirder and unsafe hacks.
        // Also such hacks wouldn't guarantee it to be more precise.
        self.tacho.make_interrupt_source(syscfg);
        self.tacho.trigger_on_edge(exti, Edge::Rising);
        self.tacho.enable_interrupt(exti);
    }

    pub fn cycle(&mut self) {
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
        }
    }

    pub fn get(&self) -> u32 {
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
    k_a: f64,
    k_b: f64,
    k_c: f64,
}