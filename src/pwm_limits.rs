use crate::channels::Channels;
use serde::{Deserialize, Serialize};
use uom::si::f64::{ElectricCurrent, ElectricPotential};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PwmLimits {
    pub max_v: ElectricPotential,
    pub max_i_pos: ElectricCurrent,
    pub max_i_neg: ElectricCurrent,
}

impl PwmLimits {
    pub fn new(channels: &mut Channels, channel: usize) -> Self {
        PwmLimits {
            max_v: channels.get_max_v(channel),
            max_i_pos: channels.get_max_i_pos(channel),
            max_i_neg: channels.get_max_i_neg(channel),
        }
    }

    pub fn apply(&self, channels: &mut Channels, channel: usize) {
        channels.set_max_v(channel, self.max_v);
        channels.set_max_i_pos(channel, self.max_i_pos);
        channels.set_max_i_neg(channel, self.max_i_neg);
    }
}
