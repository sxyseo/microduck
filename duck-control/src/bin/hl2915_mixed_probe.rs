use std::error::Error;
use std::time::{Duration, Instant};

use duck_control::bus::StaleImuTracker;
use duck_control::hl2915::{
    Hl2915WatchFaults, PRESENT_STATE_ADDR, PRESENT_STATE_EXTENDED_LEN, PresentState,
    decode_present_state, validate_ids,
};
use duck_control::imu::{IMU_BLOCK_LEN, ImuData, SflpDecoder};
use duck_control::model::{BAUD_RATE, IMU_DXL_ID};
use rustypot::DynamixelProtocolHandler;

const IMU_ADDR: u8 = 124;

fn usage() {
    eprintln!(
        "用法:\n  cargo run -p duck-control --bin hl2915_mixed_probe -- <串口> <舵机ID...> [--watch-seconds 秒]\n\n\
只读同一串口上的 HL-2915 Feetech v1 舵机和 Dynamixel v2 的 ID=200 IMU。\n\
不会写 ID、不会开扭矩、不会移动舵机。\n\
示例:\n  ... COM3 1 2\n  ... /dev/ttyUSB0 1 2 --watch-seconds 60"
    );
}

fn read_imu(
    protocol: &mut DynamixelProtocolHandler,
    serial: &mut dyn serialport::SerialPort,
    decoder: &mut SflpDecoder,
) -> Result<([u8; IMU_BLOCK_LEN], ImuData), Box<dyn Error>> {
    let blocks = protocol.sync_read(serial, &[IMU_DXL_ID], IMU_ADDR, IMU_BLOCK_LEN as u8)?;
    let block = blocks.first().ok_or("IMU did not return a data block")?;
    if block.len() != IMU_BLOCK_LEN {
        return Err(format!(
            "IMU data block length is {}, expected {IMU_BLOCK_LEN}",
            block.len()
        )
        .into());
    }
    let mut raw = [0u8; IMU_BLOCK_LEN];
    raw.copy_from_slice(block);
    let data = decoder.decode(&raw);
    Ok((raw, data))
}

fn read_motors(
    protocol: &mut DynamixelProtocolHandler,
    serial: &mut dyn serialport::SerialPort,
    ids: &[u8],
) -> Result<Vec<PresentState>, Box<dyn Error>> {
    let blocks = protocol.sync_read(serial, ids, PRESENT_STATE_ADDR, PRESENT_STATE_EXTENDED_LEN)?;
    if blocks.len() != ids.len() {
        return Err(format!(
            "motor response count is {}, expected {}",
            blocks.len(),
            ids.len()
        )
        .into());
    }
    blocks
        .iter()
        .map(|block| decode_present_state(block).map_err(|error| Box::new(error) as Box<dyn Error>))
        .collect()
}

fn print_imu(data: ImuData, ready: bool, sample: u64) {
    println!(
        "sample={sample} imu_ready={ready} gyro=[{:.3}, {:.3}, {:.3}] gravity=[{:.3}, {:.3}, {:.3}]",
        data.gyro[0], data.gyro[1], data.gyro[2], data.gravity[0], data.gravity[1], data.gravity[2]
    );
}

fn parse_u8(value: &str) -> Result<u8, Box<dyn Error>> {
    value
        .parse::<u8>()
        .map_err(|_| format!("舵机 ID 必须是 0..255 的整数：{value}").into())
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args().skip(1);
    let Some(port) = args.next() else {
        usage();
        return Ok(());
    };
    if port == "-h" || port == "--help" {
        usage();
        return Ok(());
    }

    let mut ids = Vec::new();
    let mut watch_seconds = None;
    while let Some(arg) = args.next() {
        if arg == "--watch-seconds" {
            let value = args.next().ok_or("--watch-seconds 后缺少秒数")?;
            let seconds = value
                .parse::<u64>()
                .map_err(|_| format!("秒数必须是正整数：{value}"))?;
            if seconds == 0 {
                return Err("--watch-seconds 必须大于 0".into());
            }
            watch_seconds = Some(seconds);
        } else {
            ids.push(parse_u8(&arg)?);
        }
    }
    validate_ids(&ids).map_err(|error| error.to_string())?;
    if ids.contains(&IMU_DXL_ID) {
        return Err(format!("舵机 ID 不能占用 IMU ID={IMU_DXL_ID}").into());
    }

    let serial = serialport::new(&port, BAUD_RATE)
        .timeout(Duration::from_millis(100))
        .open()
        .map_err(|error| format!("打开串口 {port} 失败：{error}"))?;
    let mut serial = serial;
    let mut v1 = DynamixelProtocolHandler::v1();
    let mut v2 = DynamixelProtocolHandler::v2();

    for &id in &ids {
        if !v1.ping(serial.as_mut(), id)? {
            return Err(format!("HL-2915 ID={id} 没有响应").into());
        }
    }
    if !v2.ping(serial.as_mut(), IMU_DXL_ID)? {
        return Err(format!("IMU ID={IMU_DXL_ID} 没有响应").into());
    }
    println!(
        "端口 {port} @ {BAUD_RATE}bps；HL-2915 v1 IDs={ids:?}；IMU v2 ID={IMU_DXL_ID}，协议切换 Ping 正常"
    );

    let mut decoder = SflpDecoder::default();
    let Some(seconds) = watch_seconds else {
        let (_, data) = read_imu(&mut v2, serial.as_mut(), &mut decoder)?;
        let states = read_motors(&mut v1, serial.as_mut(), &ids)?;
        print_imu(data, decoder.ready(), 1);
        for (id, state) in ids.iter().zip(states) {
            println!(
                "ID {id}: position={} ({:.2}°), status={}, moving={}, current={}, voltage={:.1}V, temp={}°C",
                state.position_raw,
                duck_control::hl2915::raw_to_degrees(state.position_raw),
                state
                    .status
                    .map_or_else(|| "n/a".to_owned(), |value| value.to_string()),
                state
                    .moving
                    .map_or_else(|| "n/a".to_owned(), |value| value.to_string()),
                state
                    .current_ma
                    .map_or_else(|| "n/a".to_owned(), |current| format!("{current:.1}mA")),
                state.voltage_v,
                state.temperature_c
            );
        }
        return Ok(());
    };

    let deadline = Instant::now() + Duration::from_secs(seconds);
    let mut samples = 0u64;
    let mut freshness = StaleImuTracker::default();
    let mut errors = 0u64;
    let mut motor_faults = Hl2915WatchFaults::default();
    while Instant::now() < deadline {
        let result = (|| {
            let (raw, data) = read_imu(&mut v2, serial.as_mut(), &mut decoder)?;
            let states = read_motors(&mut v1, serial.as_mut(), &ids)?;
            Ok::<_, Box<dyn Error>>((raw, data, states))
        })();
        match result {
            Ok((raw, data, states)) => {
                samples += 1;
                freshness.observe(&raw);
                for state in &states {
                    motor_faults.observe(state);
                }
                if samples == 1 || samples.is_multiple_of(25) {
                    print_imu(data, decoder.ready(), samples);
                    let min_voltage = states
                        .iter()
                        .map(|state| state.voltage_v)
                        .fold(f32::INFINITY, f32::min);
                    let max_temperature = states
                        .iter()
                        .map(|state| state.temperature_c as f32)
                        .fold(f32::NEG_INFINITY, f32::max);
                    println!(
                        "  motors: min_voltage={min_voltage:.1}V max_temperature={max_temperature:.0}°C"
                    );
                }
            }
            Err(error) => {
                errors += 1;
                eprintln!("mixed read error {errors}: {error}");
            }
        }
        std::thread::sleep(Duration::from_millis(20));
    }

    println!(
        "watch complete: samples={samples}, errors={errors}, stale_imu={}, max_stale_run={}, imu_ready={}, status_faults={}, voltage_faults={}, temperature_faults={}, current_faults={}",
        freshness.stale().total,
        freshness.max_run(),
        decoder.ready(),
        motor_faults.status,
        motor_faults.voltage,
        motor_faults.temperature,
        motor_faults.current
    );
    if errors > 0 {
        return Err(format!("混合协议读取出现 {errors} 次错误").into());
    }
    if !decoder.ready() {
        return Err("IMU 没有产生 25 个有效融合样本".into());
    }
    if freshness.frozen() {
        return Err(format!("IMU 数据连续重复 {} 帧，判定冻结", freshness.max_run()).into());
    }
    if motor_faults.any() {
        return Err(format!(
            "混合协议观察期间发现舵机异常：status={}, voltage={}, temperature={}, current={}",
            motor_faults.status,
            motor_faults.voltage,
            motor_faults.temperature,
            motor_faults.current
        )
        .into());
    }
    Ok(())
}
