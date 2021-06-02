use crate::{CHANNEL_CONFIG_KEY, ad7172, channels::{self, CHANNELS}, command_parser::PwmPin, config::ChannelConfig, dfu, flash_store::{FlashStore}, session::Session};
use channels::Channels;
use smoltcp::socket::TcpSocket;
use log::{error, warn};
use core::fmt::Write;
use crate::net;
use crate::command_parser;
use command_parser::Ipv4Config;
use command_parser::Command;
use command_parser::ShowCommand;
use crate::leds::Leds;
use uom::{
    si::{
        f64::{
            ElectricCurrent,
            ElectricPotential,
            ElectricalResistance,
            ThermodynamicTemperature,
        },
        electric_current::ampere,
        electric_potential::volt,
        electrical_resistance::ohm,
        thermodynamic_temperature::degree_celsius,
    },
};

#[derive(Debug, Clone, PartialEq)]
pub enum Handler {
    Handled,
    CloseSocket,
    NewIPV4(Ipv4Config),
    Reset,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Error {
    ParseFloat,
}

fn send_line(socket: &mut TcpSocket, data: &[u8]) -> bool {
    let send_free = socket.send_capacity() - socket.send_queue();
    if data.len() > send_free + 1 {
        // Not enough buffer space, skip report for now,
        // instead of sending incomplete line
        warn!(
            "TCP socket has only {}/{} needed {}",
            send_free + 1, socket.send_capacity(), data.len(),
        );
    } else {
        match socket.send_slice(&data) {
            Ok(sent) if sent == data.len() => {
                let _ = socket.send_slice(b"\n");
                // success
                return true
            }
            Ok(sent) =>
                warn!("sent only {}/{} bytes", sent, data.len()),
            Err(e) =>
                error!("error sending line: {:?}", e),
        }
    }
    // not success
    false
}

impl Handler {

    pub fn handle_command (command: Command, socket: &mut TcpSocket, channels: &mut Channels, session: &Session, leds: &mut Leds, store: &mut FlashStore, ipv4_config: &mut Ipv4Config) -> Result<Self, Error> {
        match command {
            Command::Quit =>
                // socket.close(),
                Ok(Handler::CloseSocket),

            Command::Reporting(_reporting) => {
                // handled by session
                send_line(socket, b"{}");
                Ok(Handler::Handled)
            }
            Command::Show(ShowCommand::Reporting) => {
                let _ = writeln!(socket, "{{ \"report\": {:?} }}", session.reporting());
                Ok(Handler::Handled)
            }
            Command::Show(ShowCommand::Input) => {
                match channels.reports_json() {
                    Ok(buf) => {
                        send_line(socket, &buf[..]);
                    }
                    Err(e) => {
                        error!("unable to serialize report: {:?}", e);
                        let _ = writeln!(socket, "{{\"error\":\"{:?}\"}}", e);

                    }
                }
                Ok(Handler::Handled)
            }
            Command::Show(ShowCommand::Pid) => {
                match channels.pid_summaries_json() {
                    Ok(buf) => {
                        send_line(socket, &buf);
                    }
                    Err(e) => {
                        error!("unable to serialize pid summary: {:?}", e);
                        let _ = writeln!(socket, "{{\"error\":\"{:?}\"}}", e);
                    }
                }
                Ok(Handler::Handled)
            }
            Command::Show(ShowCommand::Pwm) => {
                match channels.pwm_summaries_json() {
                    Ok(buf) => {
                        send_line(socket, &buf);
                    }
                    Err(e) => {
                        error!("unable to serialize pwm summary: {:?}", e);
                        let _ = writeln!(socket, "{{\"error\":\"{:?}\"}}", e);
                    }
                }
                Ok(Handler::Handled)
            }
            Command::Show(ShowCommand::SteinhartHart) => {
                match channels.steinhart_hart_summaries_json() {
                    Ok(buf) => {
                        send_line(socket, &buf);
                    }
                    Err(e) => {
                        error!("unable to serialize steinhart-hart summaries: {:?}", e);
                        let _ = writeln!(socket, "{{\"error\":\"{:?}\"}}", e);
                    }
                }
                Ok(Handler::Handled)
            }
            Command::Show(ShowCommand::PostFilter) => {
                match channels.postfilter_summaries_json() {
                    Ok(buf) => {
                        send_line(socket, &buf);
                    }
                    Err(e) => {
                        error!("unable to serialize postfilter summary: {:?}", e);
                        let _ = writeln!(socket, "{{\"error\":\"{:?}\"}}", e);
                    }
                }
                Ok(Handler::Handled)
            }
            Command::Show(ShowCommand::Ipv4) => {
                let (cidr, gateway) = net::split_ipv4_config(ipv4_config.clone());
                let _ = write!(socket, "{{\"addr\":\"{}\"", cidr);
                gateway.map(|gateway| write!(socket, ",\"gateway\":\"{}\"", gateway));
                let _ = writeln!(socket, "}}");
                Ok(Handler::Handled)
            }
            Command::PwmPid { channel } => {
                channels.channel_state(channel).pid_engaged = true;
                leds.g3.on();
                send_line(socket, b"{}");
                Ok(Handler::Handled)
            }
            Command::Pwm { channel, pin, value } => {
                match pin {
                    PwmPin::ISet => {
                        channels.channel_state(channel).pid_engaged = false;
                        leds.g3.off();
                        let current = ElectricCurrent::new::<ampere>(value);
                        channels.set_i(channel, current);
                        channels.power_up(channel);
                    }
                    PwmPin::MaxV => {
                        let voltage = ElectricPotential::new::<volt>(value);
                        channels.set_max_v(channel, voltage);
                    }
                    PwmPin::MaxIPos => {
                        let current = ElectricCurrent::new::<ampere>(value);
                        channels.set_max_i_pos(channel, current);
                    }
                    PwmPin::MaxINeg => {
                        let current = ElectricCurrent::new::<ampere>(value);
                        channels.set_max_i_neg(channel, current);
                    }
                }
                send_line(socket, b"{}");
                Ok(Handler::Handled)
            }
            Command::CenterPoint { channel, center } => {
                let i_tec = channels.get_i(channel);
                let state = channels.channel_state(channel);
                state.center = center;
                if !state.pid_engaged {
                    channels.set_i(channel, i_tec);
                }
                send_line(socket, b"{}");
                Ok(Handler::Handled)
            }
            Command::Pid { channel, parameter, value } => {
                let pid = &mut channels.channel_state(channel).pid;
                use command_parser::PidParameter::*;
                match parameter {
                    Target =>
                        pid.target = value,
                    KP =>
                        pid.parameters.kp = value as f32,
                    KI => 
                        pid.update_ki(value as f32),
                    KD =>
                        pid.parameters.kd = value as f32,
                    OutputMin =>
                        pid.parameters.output_min = value as f32,
                    OutputMax =>
                        pid.parameters.output_max = value as f32,
                    IntegralMin =>
                        pid.parameters.integral_min = value as f32,
                    IntegralMax =>
                        pid.parameters.integral_max = value as f32,
                }
                send_line(socket, b"{}");
                Ok(Handler::Handled)
            }
            Command::SteinhartHart { channel, parameter, value } => {
                let sh = &mut channels.channel_state(channel).sh;
                use command_parser::ShParameter::*;
                match parameter {
                    T0 => sh.t0 = ThermodynamicTemperature::new::<degree_celsius>(value),
                    B => sh.b = value,
                    R0 => sh.r0 = ElectricalResistance::new::<ohm>(value),
                }
                send_line(socket, b"{}");
                Ok(Handler::Handled)
            }
            Command::PostFilter { channel, rate: None } => {
                channels.adc.set_postfilter(channel as u8, None).unwrap();
                send_line(socket, b"{}");
                Ok(Handler::Handled)
            }
            Command::PostFilter { channel, rate: Some(rate) } => {
                let filter = ad7172::PostFilter::closest(rate);
                match filter {
                    Some(filter) => {
                        channels.adc.set_postfilter(channel as u8, Some(filter)).unwrap();
                        send_line(socket, b"{}");
                    }
                    None => {
                        error!("unable to choose postfilter for rate {:.3}", rate);
                        send_line(socket, b"{{\"error\": \"unable to choose postfilter rate\"}}");
                    }
                }
                Ok(Handler::Handled)
            }
            Command::Load { channel } => {
                for c in 0..CHANNELS {
                    if channel.is_none() || channel == Some(c) {
                        match store.read_value::<ChannelConfig>(CHANNEL_CONFIG_KEY[c]) {
                            Ok(Some(config)) => {
                                config.apply(channels, c);
                                send_line(socket, b"{}");
                            }
                            Ok(None) => {
                                error!("flash config not found");
                                send_line(socket, b"{{\"error\": \"flash config not found\"}}");
                            }
                            Err(e) => {
                                error!("unable to load config from flash: {:?}", e);
                                let _ = writeln!(socket, "{{\"error\":\"{:?}\"}}", e);
                            }
                        }
                    }
                }
                Ok(Handler::Handled)
            }
            Command::Save { channel } => {
                for c in 0..CHANNELS {
                    let mut store_value_buf = [0u8; 256];
                    if channel.is_none() || channel == Some(c) {
                        let config = ChannelConfig::new(channels, c);
                        match store.write_value(CHANNEL_CONFIG_KEY[c], &config, &mut store_value_buf) {
                            Ok(()) => {
                                send_line(socket, b"{}");
                            }
                            Err(e) => {
                                error!("unable to save channel {} config to flash: {:?}", c, e);
                                let _ = writeln!(socket, "{{\"error\":\"{:?}\"}}", e);
                            }
                        }
                    }
                }
                Ok(Handler::Handled)
            }
            Command::Ipv4(config) => {
                let _ = store
                    .write_value("ipv4", &config, [0; 16])
                    .map_err(|e| error!("unable to save ipv4 config to flash: {:?}", e));
                let new_ipv4_config = Some(config);
                send_line(socket, b"{}");
                Ok(Handler::NewIPV4(new_ipv4_config.unwrap()))
            }
            Command::Reset => {
                for i in 0..CHANNELS {
                    channels.power_down(i);
                }
                // should_reset = true;
                Ok(Handler::Reset)
            }
            Command::Dfu => {
                for i in 0..CHANNELS {
                    channels.power_down(i);
                }
                unsafe {
                    dfu::set_dfu_trigger();
                }
                // should_reset = true;
                Ok(Handler::Reset)
            }
        }
    }
}