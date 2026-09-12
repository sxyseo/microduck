use std::error::Error;
use std::f64::consts::PI;
use std::fs::{self, File};
use std::io::BufWriter;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use duck_control::hl2915::{
    BENCH_MAX_VOLTAGE_V, BENCH_MIN_VOLTAGE_V, BENCH_STOP_CURRENT_MA, BENCH_STOP_TEMPERATURE_C,
    Hl2915Bus, PresentState, speed_to_rad_per_second,
};
use serde::Serialize;

const COUNTS_PER_TURN: f64 = 4096.0;
#[derive(Debug)]
struct Args {
    port: String,
    id: u8,
    center_raw: u16,
    direction: i8,
    mass_kg: f64,
    arm_mass_kg: f64,
    arm_length_m: f64,
    kp: u8,
    vin: f64,
    amplitude_deg: f64,
    duration_s: f64,
    hz: f64,
    output: PathBuf,
    confirmed: bool,
}

#[derive(Serialize)]
struct BamLog {
    mass: f64,
    arm_mass: f64,
    length: f64,
    kp: u8,
    vin: f64,
    motor: &'static str,
    trajectory: &'static str,
    entries: Vec<BamEntry>,
}

#[derive(Serialize)]
struct BamEntry {
    timestamp: f64,
    goal_position: f64,
    torque_enable: bool,
    position: f64,
    speed: f64,
    load_raw: u16,
    input_volts: f32,
    temp: u8,
    current_ma: f32,
    status: u8,
    moving: u8,
}

fn usage() {
    eprintln!(
        "用法: cargo run -p duck-control --bin hl2915_bam_record -- <串口> <ID> [参数] --confirm-motion"
    );
    eprintln!("必填：--mass-kg KG --arm-length-m M --output FILE.json");
    eprintln!(
        "可选：--arm-mass-kg --center-raw --direction --kp --vin --amplitude-deg --duration-seconds --hz"
    );
    eprintln!(
        "示例：... COM3 1 --mass-kg 0.05 --arm-length-m 0.10 --output artifacts/bam/raw/kp16.json --confirm-motion"
    );
}

fn next_value(
    args: &mut impl Iterator<Item = String>,
    name: &str,
) -> Result<String, Box<dyn Error>> {
    args.next()
        .ok_or_else(|| format!("{name} 后缺少参数值").into())
}

fn parse_number<T: std::str::FromStr>(value: String, name: &str) -> Result<T, Box<dyn Error>> {
    value
        .parse::<T>()
        .map_err(|_| format!("{name} 的数值无效：{value}").into())
}

fn parse_args() -> Result<Option<Args>, Box<dyn Error>> {
    let mut values = std::env::args().skip(1);
    let Some(port) = values.next() else {
        usage();
        return Ok(None);
    };
    if matches!(port.as_str(), "-h" | "--help") {
        usage();
        return Ok(None);
    }
    let id = parse_number(next_value(&mut values, "ID")?, "ID")?;
    let mut parsed = Args {
        port,
        id,
        center_raw: 2048,
        direction: 1,
        mass_kg: f64::NAN,
        arm_mass_kg: 0.0,
        arm_length_m: f64::NAN,
        kp: 16,
        vin: 12.0,
        amplitude_deg: 10.0,
        duration_s: 6.0,
        hz: 100.0,
        output: PathBuf::new(),
        confirmed: false,
    };
    while let Some(arg) = values.next() {
        match arg.as_str() {
            "--center-raw" => {
                parsed.center_raw = parse_number(next_value(&mut values, &arg)?, &arg)?;
            }
            "--direction" => {
                parsed.direction = parse_number(next_value(&mut values, &arg)?, &arg)?;
            }
            "--mass-kg" => {
                parsed.mass_kg = parse_number(next_value(&mut values, &arg)?, &arg)?;
            }
            "--arm-mass-kg" => {
                parsed.arm_mass_kg = parse_number(next_value(&mut values, &arg)?, &arg)?;
            }
            "--arm-length-m" => {
                parsed.arm_length_m = parse_number(next_value(&mut values, &arg)?, &arg)?;
            }
            "--kp" => parsed.kp = parse_number(next_value(&mut values, &arg)?, &arg)?,
            "--vin" => parsed.vin = parse_number(next_value(&mut values, &arg)?, &arg)?,
            "--amplitude-deg" => {
                parsed.amplitude_deg = parse_number(next_value(&mut values, &arg)?, &arg)?;
            }
            "--duration-seconds" => {
                parsed.duration_s = parse_number(next_value(&mut values, &arg)?, &arg)?;
            }
            "--hz" => parsed.hz = parse_number(next_value(&mut values, &arg)?, &arg)?,
            "--output" => parsed.output = next_value(&mut values, &arg)?.into(),
            "--confirm-motion" => parsed.confirmed = true,
            _ => return Err(format!("未知参数：{arg}").into()),
        }
    }
    validate_args(&parsed)?;
    Ok(Some(parsed))
}

fn validate_args(args: &Args) -> Result<(), Box<dyn Error>> {
    if args.id >= 200 {
        return Err("舵机 ID 必须在 0..=199，200 留给 IMU".into());
    }
    if args.center_raw > 4095 {
        return Err("--center-raw 必须在 0..=4095".into());
    }
    if !matches!(args.direction, -1 | 1) {
        return Err("--direction 只能是 1 或 -1".into());
    }
    if !args.mass_kg.is_finite() || !(0.001..=1.0).contains(&args.mass_kg) {
        return Err("--mass-kg 必须在 0.001..=1.0 kg".into());
    }
    if !args.arm_mass_kg.is_finite() || !(0.0..=1.0).contains(&args.arm_mass_kg) {
        return Err("--arm-mass-kg 必须在 0..=1.0 kg".into());
    }
    if !args.arm_length_m.is_finite() || !(0.01..=0.5).contains(&args.arm_length_m) {
        return Err("--arm-length-m 必须在 0.01..=0.5 m".into());
    }
    if args.kp == 0 {
        return Err("--kp 必须在 1..=255".into());
    }
    if !args.vin.is_finite() || !(9.0..=14.0).contains(&args.vin) {
        return Err(
            "--vin 必须在当前项目保守台架门槛 9..=14 V 内；以 C001 实物手册为最终依据".into(),
        );
    }
    if !args.amplitude_deg.is_finite() || !(1.0..=30.0).contains(&args.amplitude_deg) {
        return Err("--amplitude-deg 必须在 1..=30°".into());
    }
    if !args.duration_s.is_finite() || !(2.0..=30.0).contains(&args.duration_s) {
        return Err("--duration-seconds 必须在 2..=30 秒".into());
    }
    if !args.hz.is_finite() || !(20.0..=200.0).contains(&args.hz) {
        return Err("--hz 必须在 20..=200 Hz".into());
    }
    if args.output.as_os_str().is_empty() {
        return Err("必须提供 --output FILE.json".into());
    }
    if args.output.extension().and_then(|value| value.to_str()) != Some("json") {
        return Err("--output 必须使用 .json 扩展名".into());
    }
    if !args.confirmed {
        return Err("该程序会让舵机运动；完成摆锤台架和急停检查后添加 --confirm-motion".into());
    }
    Ok(())
}

fn signed_delta(raw: u16, center_raw: u16) -> i32 {
    let mut delta = (i32::from(raw) - i32::from(center_raw)).rem_euclid(4096);
    if delta > 2048 {
        delta -= 4096;
    }
    delta
}

fn raw_to_relative_radians(raw: u16, center_raw: u16, direction: i8) -> f64 {
    f64::from(signed_delta(raw, center_raw)) * 2.0 * PI / COUNTS_PER_TURN * f64::from(direction)
}

fn relative_radians_to_raw(angle: f64, center_raw: u16, direction: i8) -> u16 {
    let delta = angle * COUNTS_PER_TURN / (2.0 * PI) * f64::from(direction);
    (i32::from(center_raw) + delta.round() as i32).rem_euclid(4096) as u16
}

fn goal_at(time_s: f64, amplitude_rad: f64) -> f64 {
    amplitude_rad * (time_s * time_s).sin()
}

fn checked_entry(
    state: PresentState,
    timestamp: f64,
    goal_position: f64,
    center_raw: u16,
    direction: i8,
) -> Result<BamEntry, Box<dyn Error>> {
    let status = state.status.unwrap_or_default();
    if status != 0 {
        return Err(format!("舵机报告故障状态 status={status}").into());
    }
    if !(BENCH_MIN_VOLTAGE_V..=BENCH_MAX_VOLTAGE_V).contains(&state.voltage_v) {
        return Err(format!("舵机反馈电压异常：{:.1} V", state.voltage_v).into());
    }
    if state.temperature_c >= BENCH_STOP_TEMPERATURE_C {
        return Err(format!("舵机温度达到停止阈值：{}°C", state.temperature_c).into());
    }
    let current_ma = state.current_ma.unwrap_or_default();
    if current_ma >= BENCH_STOP_CURRENT_MA {
        return Err(format!("舵机电流达到停止阈值：{current_ma:.1} mA").into());
    }
    Ok(BamEntry {
        timestamp,
        goal_position,
        torque_enable: true,
        position: raw_to_relative_radians(state.position_raw, center_raw, direction),
        speed: speed_to_rad_per_second(state.speed_raw) * f64::from(direction),
        load_raw: state.load_raw,
        input_volts: state.voltage_v,
        temp: state.temperature_c,
        current_ma,
        status,
        moving: state.moving.unwrap_or_default(),
    })
}

fn write_log(path: &Path, log: &BamLog) -> Result<(), Box<dyn Error>> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent)?;
    }
    serde_json::to_writer_pretty(BufWriter::new(File::create(path)?), log)?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let Some(args) = parse_args()? else {
        return Ok(());
    };
    let mut bus = Hl2915Bus::open(&args.port, &[args.id], Duration::from_millis(100))?;
    if bus.ping_all()? != [args.id] {
        return Err(format!("HL-2915 ID={} 没有响应", args.id).into());
    }
    let initial = bus.read_states()?.remove(0);
    checked_entry(initial, 0.0, 0.0, args.center_raw, args.direction)?;
    let start_offset_deg =
        raw_to_relative_radians(initial.position_raw, args.center_raw, args.direction)
            .to_degrees()
            .abs();
    if start_offset_deg > args.amplitude_deg + 5.0 {
        return Err(format!(
            "当前摆臂离竖直零位 {start_offset_deg:.1}°，超过安全起始范围；断电后手动回零"
        )
        .into());
    }

    println!(
        "即将运行单舵机摆锤：端口={} ID={} P={} 幅度=±{:.1}° 时长={:.1}s；I=D=0",
        args.port, args.id, args.kp, args.amplitude_deg, args.duration_s
    );
    bus.set_pid_gains(args.kp, 0, 0)?;
    bus.write_positions_raw(&[initial.position_raw])?;
    bus.set_torque(true)?;

    let result = (|| {
        let period = Duration::from_secs_f64(1.0 / args.hz);
        let amplitude_rad = args.amplitude_deg.to_radians();
        let started = Instant::now();
        let mut entries = Vec::new();
        let mut last_goal = 0.0;
        while started.elapsed().as_secs_f64() < args.duration_s {
            let cycle = Instant::now();
            let timestamp = started.elapsed().as_secs_f64();
            let goal = goal_at(timestamp, amplitude_rad);
            let target = relative_radians_to_raw(goal, args.center_raw, args.direction);
            bus.write_positions_raw(&[target])?;
            let state = bus.read_states()?.remove(0);
            entries.push(checked_entry(
                state,
                timestamp,
                goal,
                args.center_raw,
                args.direction,
            )?);
            last_goal = goal;
            std::thread::sleep(period.saturating_sub(cycle.elapsed()));
        }

        for step in 1..=100 {
            let goal = last_goal * (1.0 - f64::from(step) / 100.0);
            bus.write_positions_raw(&[relative_radians_to_raw(
                goal,
                args.center_raw,
                args.direction,
            )])?;
            let state = bus.read_states()?.remove(0);
            checked_entry(
                state,
                args.duration_s + f64::from(step) * 0.01,
                goal,
                args.center_raw,
                args.direction,
            )?;
            std::thread::sleep(Duration::from_millis(10));
        }

        let log = BamLog {
            mass: args.mass_kg,
            arm_mass: args.arm_mass_kg,
            length: args.arm_length_m,
            kp: args.kp,
            vin: args.vin,
            motor: "hl2915",
            trajectory: "scaled_sin_time_square",
            entries,
        };
        if log.entries.len() < 2 {
            return Err("有效采样不足 2 条".into());
        }
        write_log(&args.output, &log)?;
        println!(
            "记录完成：samples={} output={}",
            log.entries.len(),
            args.output.display()
        );
        Ok::<_, Box<dyn Error>>(())
    })();

    let torque_off = bus.set_torque(false);
    if let Err(error) = result {
        if let Err(off_error) = torque_off {
            eprintln!("摆锤失败后关闭扭矩也失败：{off_error}");
        }
        return Err(error);
    }
    torque_off?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn relative_position_wraps_and_honors_direction() {
        let one_count = 2.0 * PI / COUNTS_PER_TURN;
        assert!((raw_to_relative_radians(1, 0, 1) - one_count).abs() < 1e-12);
        assert!((raw_to_relative_radians(4095, 0, 1) + one_count).abs() < 1e-12);
        assert!((raw_to_relative_radians(1, 0, -1) + one_count).abs() < 1e-12);
    }

    #[test]
    fn relative_target_round_trips_near_center() {
        for angle in [-0.5, 0.0, 0.5] {
            let raw = relative_radians_to_raw(angle, 2048, -1);
            let decoded = raw_to_relative_radians(raw, 2048, -1);
            assert!((decoded - angle).abs() <= PI / COUNTS_PER_TURN);
        }
    }

    #[test]
    fn trajectory_never_exceeds_requested_amplitude() {
        let amplitude = 10.0_f64.to_radians();
        for sample in 0..=600 {
            assert!(goal_at(f64::from(sample) / 100.0, amplitude).abs() <= amplitude);
        }
    }
}
