use std::collections::HashSet;
use std::f64::consts::PI;
use std::time::Duration;

use rustypot::DynamixelProtocolHandler;
use rustypot::servo::feetech::sts3215::Sts3215Controller;
use thiserror::Error;

use crate::bus::StaleImuTracker;
use crate::imu::{IMU_BLOCK_LEN, SflpDecoder};
use crate::io::{
    ImuStale, IoError, JointTargets, Result as IoResult, RobotIo, Sensors, SlowSensors,
};
use crate::model::NUM_JOINTS;

/// HL-2915-C001 uses the Feetech magnetic-servo protocol (protocol v1).
pub const DEFAULT_BAUD_RATE: u32 = 1_000_000;
pub const PRESENT_STATE_ADDR: u8 = 56;
pub const PRESENT_STATE_LEN: u8 = 8;
pub const PRESENT_STATE_EXTENDED_LEN: u8 = 15;
pub const POSITION_CENTER: u16 = 2048;
/// ID reserved by this project for the protocol-v2 IMU board.
pub const RESERVED_IMU_ID: u8 = 200;
pub const DEFAULT_HL2915_IDS: [u8; NUM_JOINTS] =
    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15];
/// Conservative first-bring-up limits, lower than the servo's own protection settings.
pub const BENCH_MIN_VOLTAGE_V: f32 = 9.0;
pub const BENCH_MAX_VOLTAGE_V: f32 = 14.0;
pub const BENCH_STOP_TEMPERATURE_C: u8 = 55;
pub const BENCH_STOP_CURRENT_MA: f32 = 1_400.0;
const GOAL_POSITION_ADDR: u8 = 42;
const TORQUE_ENABLE_ADDR: u8 = 40;
const P_GAIN_ADDR: u8 = 21;
const D_GAIN_ADDR: u8 = 22;
const I_GAIN_ADDR: u8 = 23;
const PRESENT_VOLTAGE_ADDR: u8 = 62;
const IMU_ADDR: u8 = 124;
const CURRENT_OFFSET: usize = 13;
const CURRENT_MA_PER_COUNT: f64 = 6.5;
// HLS magnetic-servo memory table: present speed is 0.732 RPM per count.
// This is deliberately not the XL330/Dynamixel 0.229 RPM tick.
const SPEED_RPM_PER_COUNT: f64 = 0.732;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PresentState {
    pub position_raw: u16,
    pub speed_raw: u16,
    pub load_raw: u16,
    pub status: Option<u8>,
    pub moving: Option<u8>,
    pub voltage_v: f32,
    pub temperature_c: u8,
    pub current_raw: Option<u16>,
    pub current_ma: Option<f32>,
}

/// Fault counters used by the read-only HL-2915 bench probes.
///
/// The limits are deliberately conservative for the first unloaded bring-up: this project gate
/// accepts only 9–14 V, stops at 55 °C, and stops at 1.4 A. The C001 specification lists a higher
/// internal overheat protection point and about 1.5 A stall current; the lower software limits are
/// an early-warning gate, not a replacement for the servo's own protection. A real robot may later
/// use measured per-joint limits, but a bench probe must not silently pass a motor already at the
/// edge of stall.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct Hl2915WatchFaults {
    pub status: u64,
    pub voltage: u64,
    pub temperature: u64,
    pub current: u64,
}

impl Hl2915WatchFaults {
    pub fn observe(&mut self, state: &PresentState) {
        if state.status.unwrap_or_default() != 0 {
            self.status += 1;
        }
        if !(BENCH_MIN_VOLTAGE_V..=BENCH_MAX_VOLTAGE_V).contains(&state.voltage_v) {
            self.voltage += 1;
        }
        if state.temperature_c >= BENCH_STOP_TEMPERATURE_C {
            self.temperature += 1;
        }
        if state.current_ma.unwrap_or_default() >= BENCH_STOP_CURRENT_MA {
            self.current += 1;
        }
    }

    pub fn any(self) -> bool {
        self != Self::default()
    }
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum DecodeError {
    #[error("present state needs 8 bytes, got {0}")]
    Short(usize),
    #[error("sync read returned {got} servo states, expected {expected}")]
    Count { expected: usize, got: usize },
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum IdError {
    #[error("at least one servo ID is required")]
    Empty,
    #[error("servo ID {0} is broadcast/reserved; use IDs 0..=253")]
    Broadcast(u8),
    #[error("servo ID {0} is reserved for the project IMU")]
    Reserved(u8),
    #[error("servo ID {0} appears more than once")]
    Duplicate(u8),
}

#[derive(Debug, Error, PartialEq)]
pub enum PositionError {
    #[error("expected {expected} positions, got {got}")]
    Count { expected: usize, got: usize },
    #[error("position {value} at index {index} is outside 0..=4095")]
    Range { index: usize, value: u16 },
    #[error("angle {0}° is outside the supported range 0°..360°")]
    AngleOutOfRange(f64),
    #[error("joint angle {0} rad is outside the supported range -π..π")]
    RadiansOutOfRange(f64),
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum CalibrationError {
    #[error("zero position {0} is outside 0..=4095")]
    ZeroOutOfRange(u16),
    #[error("direction must be +1 or -1, got {0}")]
    Direction(i8),
}

/// Per-joint encoder calibration for the HL-2915 backend.
///
/// `zero_raw` is the encoder value at the mechanical joint's zero angle. `direction` maps a
/// positive model angle to a positive (`+1`) or negative (`-1`) encoder delta. The defaults are
/// deliberately only a bench starting point; a printed robot must be calibrated joint by joint.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FeetechCalibration {
    pub zero_raw: [u16; NUM_JOINTS],
    pub direction: [i8; NUM_JOINTS],
}

impl Default for FeetechCalibration {
    fn default() -> Self {
        Self {
            zero_raw: [POSITION_CENTER; NUM_JOINTS],
            direction: [1; NUM_JOINTS],
        }
    }
}

impl FeetechCalibration {
    pub fn validate(&self) -> std::result::Result<(), CalibrationError> {
        for &zero in &self.zero_raw {
            if zero > 4095 {
                return Err(CalibrationError::ZeroOutOfRange(zero));
            }
        }
        for &direction in &self.direction {
            if !matches!(direction, -1 | 1) {
                return Err(CalibrationError::Direction(direction));
            }
        }
        Ok(())
    }

    pub fn raw_to_radians(&self, joint: usize, raw: u16) -> f64 {
        let mut delta = (i32::from(raw) - i32::from(self.zero_raw[joint])).rem_euclid(4096);
        if delta > 2048 {
            delta -= 4096;
        }
        f64::from(delta) * (2.0 * PI / 4096.0) * f64::from(self.direction[joint])
    }

    pub fn radians_to_raw(
        &self,
        joint: usize,
        angle: f64,
    ) -> std::result::Result<u16, PositionError> {
        if !angle.is_finite() || !(-PI..=PI).contains(&angle) {
            return Err(PositionError::RadiansOutOfRange(angle));
        }
        let delta = angle * 4096.0 / (2.0 * PI) * f64::from(self.direction[joint]);
        Ok((i32::from(self.zero_raw[joint]) + delta.round() as i32).rem_euclid(4096) as u16)
    }
}

/// Decode the state bytes returned by a read starting at address 56.
///
/// The first 8 bytes are always present. A 15-byte read additionally supplies the status and
/// moving flags plus the present-current register; the optional fields stay `None` for the short
/// read so the bench decoder can be reused by a minimal device query.
pub fn decode_present_state(data: &[u8]) -> Result<PresentState, DecodeError> {
    if data.len() < PRESENT_STATE_LEN as usize {
        return Err(DecodeError::Short(data.len()));
    }
    Ok(PresentState {
        position_raw: u16::from_le_bytes([data[0], data[1]]),
        speed_raw: u16::from_le_bytes([data[2], data[3]]),
        load_raw: u16::from_le_bytes([data[4], data[5]]),
        status: data.get(9).copied(),
        moving: data.get(10).copied(),
        voltage_v: data[6] as f32 * 0.1,
        temperature_c: data[7],
        current_raw: data
            .get(CURRENT_OFFSET + 1)
            .map(|_| u16::from_le_bytes([data[CURRENT_OFFSET], data[CURRENT_OFFSET + 1]]) & 0x7fff),
        current_ma: data.get(CURRENT_OFFSET + 1).map(|_| {
            f32::from(u16::from_le_bytes([data[CURRENT_OFFSET], data[CURRENT_OFFSET + 1]]) & 0x7fff)
                * CURRENT_MA_PER_COUNT as f32
        }),
    })
}

fn ensure_response_count(expected: usize, got: usize) -> Result<(), DecodeError> {
    if expected == got {
        Ok(())
    } else {
        Err(DecodeError::Count { expected, got })
    }
}

/// Return a human-readable safety fault for one live actuator sample.
///
/// Keep the thresholds identical to [`Hl2915WatchFaults`], but return the first sample's reason
/// so the runtime can stop immediately instead of waiting for an aggregate bench report.
pub fn present_state_fault(state: &PresentState) -> Option<String> {
    let mut reasons = Vec::new();
    if let Some(status) = state.status.filter(|status| *status != 0) {
        reasons.push(format!("status={status}"));
    }
    if !(BENCH_MIN_VOLTAGE_V..=BENCH_MAX_VOLTAGE_V).contains(&state.voltage_v) {
        reasons.push(format!("voltage={:.1}V", state.voltage_v));
    }
    if state.temperature_c >= BENCH_STOP_TEMPERATURE_C {
        reasons.push(format!("temperature={}C", state.temperature_c));
    }
    if let Some(current_ma) = state
        .current_ma
        .filter(|current| *current >= BENCH_STOP_CURRENT_MA)
    {
        reasons.push(format!("current={current_ma:.0}mA"));
    }
    (!reasons.is_empty()).then(|| reasons.join(", "))
}

pub fn speed_to_rad_per_second(raw: u16) -> f64 {
    let magnitude = f64::from(raw & 0x7fff) * SPEED_RPM_PER_COUNT;
    let sign = if raw & 0x8000 != 0 { -1.0 } else { 1.0 };
    sign * magnitude * 2.0 * PI / 60.0
}

pub fn raw_to_degrees(raw: u16) -> f64 {
    f64::from(raw.min(4095)) * 360.0 / 4096.0
}

pub fn degrees_to_raw(degrees: f64) -> Result<u16, PositionError> {
    if !degrees.is_finite() || !(0.0..360.0).contains(&degrees) {
        return Err(PositionError::AngleOutOfRange(degrees));
    }
    Ok(((degrees * 4096.0 / 360.0).round() as u16).min(4095))
}

pub fn validate_ids(ids: &[u8]) -> Result<(), IdError> {
    if ids.is_empty() {
        return Err(IdError::Empty);
    }
    let mut seen = HashSet::with_capacity(ids.len());
    for &id in ids {
        if id == 254 || id == 255 {
            return Err(IdError::Broadcast(id));
        }
        if id == RESERVED_IMU_ID {
            return Err(IdError::Reserved(id));
        }
        if !seen.insert(id) {
            return Err(IdError::Duplicate(id));
        }
    }
    Ok(())
}

/// Small, safe bench controller for one or two HL-2915-C001 servos.
///
/// It deliberately exposes raw register units first. This keeps calibration visible and avoids
/// silently applying the XL330 angle convention to a Feetech motor.
pub struct Hl2915Bus {
    controller: Sts3215Controller,
    ids: Vec<u8>,
}

/// A full `RobotIo` backend for 15 HL-2915 servos plus the existing protocol-v2 IMU board.
///
/// The two protocol handlers share one serial port but never share a packet: each transaction
/// finishes before the other protocol is sent. This is the smallest safe bridge from the bench
/// probe to `robotd`; the default backend remains the XL330 implementation until the HL bus has
/// passed the documented two-servo and IMU gates.
pub struct Hl2915RobotIo {
    serial: Box<dyn serialport::SerialPort>,
    v1: DynamixelProtocolHandler,
    v2: DynamixelProtocolHandler,
    ids: Vec<u8>,
    imu_id: u8,
    calibration: FeetechCalibration,
    imu: SflpDecoder,
    stale_imu: StaleImuTracker,
}

impl Hl2915RobotIo {
    pub fn open(
        port: &str,
        ids: &[u8],
        imu_id: u8,
        calibration: FeetechCalibration,
        timeout: Duration,
    ) -> IoResult<Self> {
        validate_ids(ids).map_err(|e| IoError::Bus(e.to_string()))?;
        if ids.len() != NUM_JOINTS {
            return Err(IoError::ShortRead {
                what: "HL-2915 joint IDs",
                expected: NUM_JOINTS,
                got: ids.len(),
            });
        }
        if ids.contains(&imu_id) {
            return Err(IoError::Bus(format!(
                "HL-2915 joint IDs contain IMU ID {imu_id}"
            )));
        }
        calibration
            .validate()
            .map_err(|e| IoError::Bus(e.to_string()))?;
        let serial = serialport::new(port, DEFAULT_BAUD_RATE)
            .timeout(timeout)
            .open()
            .map_err(|e| IoError::Port {
                path: port.to_owned(),
                source: std::io::Error::other(e),
            })?;
        Ok(Self {
            serial,
            v1: DynamixelProtocolHandler::v1(),
            v2: DynamixelProtocolHandler::v2(),
            ids: ids.to_vec(),
            imu_id,
            calibration,
            imu: SflpDecoder::default(),
            stale_imu: StaleImuTracker::default(),
        })
    }

    /// Ping every HL-2915 and the v2 IMU before `robotd` starts a control loop.
    pub fn check_devices(&mut self) -> IoResult<()> {
        for &id in &self.ids {
            if !self
                .v1
                .ping(self.serial.as_mut(), id)
                .map_err(|e| IoError::Bus(format!("ping HL-2915 {id}: {e}")))?
            {
                return Err(IoError::Bus(format!("HL-2915 {id} did not answer")));
            }
        }
        if !self
            .v2
            .ping(self.serial.as_mut(), self.imu_id)
            .map_err(|e| IoError::Bus(format!("ping IMU {0}: {e}", self.imu_id)))?
        {
            return Err(IoError::Bus(format!("IMU {} did not answer", self.imu_id)));
        }
        Ok(())
    }

    pub fn present_positions(&mut self) -> IoResult<[f64; NUM_JOINTS]> {
        let blocks = self
            .v1
            .sync_read(self.serial.as_mut(), &self.ids, PRESENT_STATE_ADDR, 2)
            .map_err(|e| IoError::Bus(format!("read HL-2915 positions: {e}")))?;
        if blocks.len() != NUM_JOINTS {
            return Err(IoError::ShortRead {
                what: "HL-2915 positions",
                expected: NUM_JOINTS,
                got: blocks.len(),
            });
        }
        let mut positions = [0.0; NUM_JOINTS];
        for (joint, block) in blocks.iter().enumerate() {
            if block.len() != 2 {
                return Err(IoError::ShortRead {
                    what: "HL-2915 position block",
                    expected: 2,
                    got: block.len(),
                });
            }
            positions[joint] = self
                .calibration
                .raw_to_radians(joint, u16::from_le_bytes([block[0], block[1]]));
        }
        Ok(positions)
    }

    pub fn interpolate_to(
        &mut self,
        target: &[f64; NUM_JOINTS],
        duration: Duration,
        step: Duration,
    ) -> IoResult<()> {
        let start = self.present_positions()?;
        let steps = (duration.as_secs_f64() / step.as_secs_f64())
            .ceil()
            .max(1.0) as u32;
        for i in 1..=steps {
            let t = i as f64 / steps as f64;
            let mut next = [0.0; NUM_JOINTS];
            for joint in 0..NUM_JOINTS {
                next[joint] = start[joint] + (target[joint] - start[joint]) * t;
            }
            self.write(&JointTargets::new(next))?;
            std::thread::sleep(step);
        }
        Ok(())
    }

    fn write_register(&mut self, addr: u8, data: &[Vec<u8>]) -> IoResult<()> {
        self.v1
            .sync_write(self.serial.as_mut(), &self.ids, addr, data)
            .map_err(|e| IoError::Bus(format!("HL-2915 sync_write address {addr}: {e}")))
    }
}

impl RobotIo for Hl2915RobotIo {
    fn read(&mut self) -> IoResult<Sensors> {
        let imu_blocks = self
            .v2
            .sync_read(
                self.serial.as_mut(),
                &[self.imu_id],
                IMU_ADDR,
                IMU_BLOCK_LEN as u8,
            )
            .map_err(|e| IoError::Bus(format!("read IMU block: {e}")))?;
        let imu_block = imu_blocks.first().ok_or(IoError::ShortRead {
            what: "IMU blocks",
            expected: 1,
            got: imu_blocks.len(),
        })?;
        if imu_block.len() != IMU_BLOCK_LEN {
            return Err(IoError::ShortRead {
                what: "IMU block",
                expected: IMU_BLOCK_LEN,
                got: imu_block.len(),
            });
        }
        let mut raw_imu = [0u8; IMU_BLOCK_LEN];
        raw_imu.copy_from_slice(imu_block);
        self.stale_imu.observe(&raw_imu);

        let blocks = self
            .v1
            .sync_read(
                self.serial.as_mut(),
                &self.ids,
                PRESENT_STATE_ADDR,
                PRESENT_STATE_EXTENDED_LEN,
            )
            .map_err(|e| IoError::Bus(format!("read HL-2915 state: {e}")))?;
        if blocks.len() != NUM_JOINTS {
            return Err(IoError::ShortRead {
                what: "HL-2915 state blocks",
                expected: NUM_JOINTS,
                got: blocks.len(),
            });
        }

        let mut sensors = Sensors {
            imu: self.imu.decode(&raw_imu),
            ..Sensors::default()
        };
        for (joint, block) in blocks.iter().enumerate() {
            if block.len() != PRESENT_STATE_EXTENDED_LEN as usize {
                return Err(IoError::ShortRead {
                    what: "HL-2915 state block",
                    expected: PRESENT_STATE_EXTENDED_LEN as usize,
                    got: block.len(),
                });
            }
            let state = decode_present_state(block)
                .map_err(|e| IoError::Bus(format!("decode HL-2915 joint {joint}: {e}")))?;
            if let Some(reason) = present_state_fault(&state) {
                return Err(IoError::ActuatorFault(format!(
                    "HL-2915 joint {joint}: {reason}"
                )));
            }
            sensors.positions[joint] = self.calibration.raw_to_radians(joint, state.position_raw);
            sensors.velocities[joint] = speed_to_rad_per_second(state.speed_raw);
            sensors.currents_ma[joint] =
                f64::from(state.current_raw.unwrap_or_default()) * CURRENT_MA_PER_COUNT;
        }
        Ok(sensors)
    }

    fn write(&mut self, targets: &JointTargets) -> IoResult<()> {
        let mut data = Vec::with_capacity(NUM_JOINTS);
        for (joint, &angle) in targets.positions.iter().enumerate() {
            let raw = self
                .calibration
                .radians_to_raw(joint, angle)
                .map_err(|e| IoError::Bus(format!("HL-2915 joint {joint}: {e}")))?;
            data.push(raw.to_le_bytes().to_vec());
        }
        self.write_register(GOAL_POSITION_ADDR, &data)
    }

    fn set_torque(&mut self, on: bool) -> IoResult<()> {
        let value = vec![on as u8];
        self.write_register(TORQUE_ENABLE_ADDR, &vec![value; NUM_JOINTS])
    }

    fn reboot(&mut self, id: u8) -> IoResult<()> {
        // The status packet is a courtesy the servo may not manage before it resets, so only a
        // failure to send is an error here.
        self.v1
            .reboot(self.serial.as_mut(), id)
            .map(|_| ())
            .map_err(|e| IoError::Bus(format!("HL-2915 reboot {id}: {e}")))
    }

    fn set_gain(&mut self, kp: u16) -> IoResult<()> {
        // Feetech's P/I/D registers are one byte and do not share XL330's scale. This is a
        // deliberately conservative bridge: it keeps the control path functional, while the
        // HL-2915 tuning pass must measure a better mapping before walking is enabled.
        let p = vec![vec![kp.min(255) as u8]; NUM_JOINTS];
        let zero = vec![vec![0u8]; NUM_JOINTS];
        self.write_register(P_GAIN_ADDR, &p)?;
        self.write_register(D_GAIN_ADDR, &zero)?;
        self.write_register(I_GAIN_ADDR, &zero)
    }

    fn slow_sensors(&mut self) -> IoResult<SlowSensors> {
        let blocks = self
            .v1
            .sync_read(self.serial.as_mut(), &self.ids, PRESENT_VOLTAGE_ADDR, 2)
            .map_err(|e| IoError::Bus(format!("read HL-2915 voltage+temperature: {e}")))?;
        if blocks.len() != NUM_JOINTS {
            return Err(IoError::ShortRead {
                what: "HL-2915 voltage+temperature blocks",
                expected: NUM_JOINTS,
                got: blocks.len(),
            });
        }
        let mut volts = Vec::with_capacity(NUM_JOINTS);
        let mut temps_c = [0.0; NUM_JOINTS];
        for (joint, block) in blocks.iter().enumerate() {
            if block.len() != 2 {
                return Err(IoError::ShortRead {
                    what: "HL-2915 voltage+temperature block",
                    expected: 2,
                    got: block.len(),
                });
            }
            volts.push(f64::from(block[0]) * 0.1);
            temps_c[joint] = f64::from(block[1]);
        }
        Ok(SlowSensors {
            volts: volts.iter().sum::<f64>() / volts.len() as f64,
            temps_c,
        })
    }

    fn imu_stale(&self) -> ImuStale {
        self.stale_imu.stale()
    }

    fn imu_ready(&self) -> bool {
        self.imu.ready()
    }
}

impl Hl2915Bus {
    pub fn open(
        port: &str,
        ids: &[u8],
        timeout: Duration,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        validate_ids(ids)?;
        let serial = serialport::new(port, DEFAULT_BAUD_RATE)
            .timeout(timeout)
            .open()?;
        let controller = Sts3215Controller::new()
            .with_protocol_v1()
            .with_serial_port(serial);
        Ok(Self {
            controller,
            ids: ids.to_vec(),
        })
    }

    pub fn ids(&self) -> &[u8] {
        &self.ids
    }

    pub fn ping_all(&mut self) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
        let mut found = Vec::new();
        for &id in &self.ids {
            if self.controller.ping(id)? {
                found.push(id);
            }
        }
        Ok(found)
    }

    pub fn read_states(&mut self) -> Result<Vec<PresentState>, Box<dyn std::error::Error>> {
        let blocks = self.controller.sync_read_raw_data(
            &self.ids,
            PRESENT_STATE_ADDR,
            PRESENT_STATE_EXTENDED_LEN,
        )?;
        ensure_response_count(self.ids.len(), blocks.len())
            .map_err(|error| Box::new(error) as Box<dyn std::error::Error>)?;
        blocks
            .iter()
            .map(|block| decode_present_state(block).map_err(|e| Box::new(e) as _))
            .collect()
    }

    pub fn set_torque(&mut self, on: bool) -> Result<(), Box<dyn std::error::Error>> {
        self.controller
            .sync_write_torque_enable(&self.ids, &vec![on; self.ids.len()])?;
        Ok(())
    }

    pub fn set_pid_gains(&mut self, p: u8, i: u8, d: u8) -> Result<(), Box<dyn std::error::Error>> {
        self.controller
            .sync_write_p_coefficient(&self.ids, &vec![p; self.ids.len()])?;
        self.controller
            .sync_write_i_coefficient(&self.ids, &vec![i; self.ids.len()])?;
        self.controller
            .sync_write_d_coefficient(&self.ids, &vec![d; self.ids.len()])?;
        Ok(())
    }

    pub fn set_id(&mut self, current_id: u8, new_id: u8) -> Result<(), Box<dyn std::error::Error>> {
        validate_ids(&[new_id])?;
        self.controller.write_id(current_id, new_id)?;
        Ok(())
    }

    pub fn write_positions_raw(
        &mut self,
        positions: &[u16],
    ) -> Result<(), Box<dyn std::error::Error>> {
        if positions.len() != self.ids.len() {
            return Err(Box::new(PositionError::Count {
                expected: self.ids.len(),
                got: positions.len(),
            }));
        }
        for (index, &value) in positions.iter().enumerate() {
            if value > 4095 {
                return Err(Box::new(PositionError::Range { index, value }));
            }
        }
        let values: Vec<i16> = positions.iter().map(|&value| value as i16).collect();
        self.controller
            .sync_write_raw_goal_position(&self.ids, &values)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decodes_the_extended_present_state_block() {
        let state = decode_present_state(&[
            0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x79, 0x1e, 0, 0, 0, 0, 0, 0x0a, 0x00,
        ])
        .expect("valid state block");
        assert_eq!(state.position_raw, 2048);
        assert_eq!(state.speed_raw, 0);
        assert_eq!(state.load_raw, 0);
        assert_eq!(state.status, Some(0));
        assert_eq!(state.moving, Some(0));
        assert!((state.voltage_v - 12.1).abs() < f32::EPSILON);
        assert_eq!(state.temperature_c, 30);
        assert_eq!(state.current_raw, Some(10));
        assert_eq!(state.current_ma, Some(65.0));
    }

    #[test]
    fn short_present_state_keeps_optional_fields_absent() {
        let state = decode_present_state(&[0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x79, 0x1e])
            .expect("valid short state block");
        assert_eq!(state.position_raw, 2048);
        assert_eq!(state.status, None);
        assert_eq!(state.moving, None);
        assert_eq!(state.current_raw, None);
        assert_eq!(state.current_ma, None);
    }

    #[test]
    fn rejects_short_state_blocks() {
        assert!(decode_present_state(&[0; 7]).is_err());
    }

    #[test]
    fn rejects_partial_sync_read_responses() {
        assert!(ensure_response_count(2, 1).is_err());
        assert!(ensure_response_count(2, 2).is_ok());
    }

    #[test]
    fn degrees_round_trip_at_the_center() {
        assert_eq!(degrees_to_raw(180.0).expect("in range"), 2048);
        assert!((raw_to_degrees(2048) - 180.0).abs() < 0.001);
    }

    #[test]
    fn degrees_near_full_turn_stays_in_register_range() {
        assert_eq!(degrees_to_raw(359.999).expect("in range"), 4095);
        assert!(degrees_to_raw(360.0).is_err());
    }

    #[test]
    fn ids_are_unique_and_not_broadcast() {
        assert!(validate_ids(&[1, 2]).is_ok());
        assert!(validate_ids(&[1, 1]).is_err());
        assert!(validate_ids(&[1, 254]).is_err());
        assert!(matches!(
            validate_ids(&[RESERVED_IMU_ID]),
            Err(IdError::Reserved(200))
        ));
    }

    #[test]
    fn calibration_round_trips_direction_and_zero() {
        let mut calibration = FeetechCalibration::default();
        calibration.zero_raw[0] = 1000;
        calibration.direction[0] = -1;
        calibration.validate().expect("valid calibration");
        let raw = calibration.radians_to_raw(0, 0.5).expect("angle in range");
        let angle = calibration.raw_to_radians(0, raw);
        assert!((angle - 0.5).abs() < 2.0 * PI / 4096.0);
        assert_eq!(calibration.raw_to_radians(0, 1000), 0.0);
    }

    #[test]
    fn calibration_rejects_bad_direction() {
        let mut calibration = FeetechCalibration::default();
        calibration.direction[3] = 0;
        assert!(matches!(
            calibration.validate(),
            Err(CalibrationError::Direction(0))
        ));
    }

    #[test]
    fn hls_speed_uses_feetech_scale_and_sign_bit() {
        let one_count = speed_to_rad_per_second(1);
        let reverse = speed_to_rad_per_second(0x8001);
        let expected = 0.732 * 2.0 * PI / 60.0;
        assert!((one_count - expected).abs() < 1e-12);
        assert!((reverse + expected).abs() < 1e-12);
    }

    #[test]
    fn watch_health_counts_each_motor_fault_category() {
        let mut faults = Hl2915WatchFaults::default();
        faults.observe(&PresentState {
            position_raw: 2048,
            speed_raw: 0,
            load_raw: 0,
            status: Some(4),
            moving: Some(0),
            voltage_v: 8.9,
            temperature_c: 55,
            current_raw: Some(216),
            current_ma: Some(1_404.0),
        });

        assert_eq!(faults.status, 1);
        assert_eq!(faults.voltage, 1);
        assert_eq!(faults.temperature, 1);
        assert_eq!(faults.current, 1);
        assert!(faults.any());
    }

    #[test]
    fn present_state_fault_matches_bench_stop_thresholds() {
        let state = PresentState {
            position_raw: 2048,
            speed_raw: 0,
            load_raw: 0,
            status: Some(2),
            moving: Some(0),
            voltage_v: 8.9,
            temperature_c: 55,
            current_raw: Some(216),
            current_ma: Some(1_404.0),
        };
        let reason = present_state_fault(&state).expect("fault must be reported");
        assert!(reason.contains("status=2"));
        assert!(reason.contains("voltage=8.9V"));
        assert!(reason.contains("temperature=55C"));
        assert!(reason.contains("current=1404mA"));
    }

    #[test]
    fn present_state_fault_accepts_a_nominal_sample() {
        let state = PresentState {
            position_raw: 2048,
            speed_raw: 0,
            load_raw: 0,
            status: Some(0),
            moving: Some(0),
            voltage_v: 12.0,
            temperature_c: 30,
            current_raw: Some(10),
            current_ma: Some(65.0),
        };
        assert!(present_state_fault(&state).is_none());
    }
}
