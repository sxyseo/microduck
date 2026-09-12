use std::error::Error;
use std::time::{Duration, Instant};

use duck_control::bus::StaleImuTracker;
use duck_control::imu::{IMU_BLOCK_LEN, ImuData, SflpDecoder};
use duck_control::model::{BAUD_RATE, IMU_DXL_ID};
use rustypot::DynamixelProtocolHandler;

const IMU_ADDR: u8 = 124;

fn usage() {
    eprintln!(
        "用法:\n  cargo run -p duck-control --bin imu_probe -- <串口> [--watch-seconds 秒]\n\n\
只读 Dynamixel Protocol v2 的 ID=200 IMU，不会访问舵机。\n\
示例:\n  ... /dev/ttyUSB0\n  ... /dev/ttyS2 --watch-seconds 10"
    );
}

fn read_once(
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

fn print_sample(data: ImuData, ready: bool, sample: u64) {
    println!(
        "sample={sample} ready={ready} gyro=[{:.3}, {:.3}, {:.3}] rad/s gravity=[{:.3}, {:.3}, {:.3}]",
        data.gyro[0], data.gyro[1], data.gyro[2], data.gravity[0], data.gravity[1], data.gravity[2]
    );
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

    let mut watch_seconds = None;
    while let Some(arg) = args.next() {
        if arg != "--watch-seconds" {
            return Err(format!("未知参数：{arg}").into());
        }
        let value = args.next().ok_or("--watch-seconds 后缺少秒数")?;
        let seconds = value
            .parse::<u64>()
            .map_err(|_| format!("秒数必须是正整数：{value}"))?;
        if seconds == 0 {
            return Err("--watch-seconds 必须大于 0".into());
        }
        watch_seconds = Some(seconds);
    }

    let serial = serialport::new(&port, BAUD_RATE)
        .timeout(Duration::from_millis(100))
        .open()
        .map_err(|error| format!("打开串口 {port} 失败：{error}"))?;
    let mut serial = serial;
    let mut protocol = DynamixelProtocolHandler::v2();
    if !protocol.ping(serial.as_mut(), IMU_DXL_ID)? {
        return Err(format!("IMU ID={IMU_DXL_ID} 没有响应").into());
    }
    println!("端口 {port} @ {BAUD_RATE}bps；IMU ID={IMU_DXL_ID} 响应正常");

    let mut decoder = SflpDecoder::default();
    let Some(seconds) = watch_seconds else {
        let (_, data) = read_once(&mut protocol, serial.as_mut(), &mut decoder)?;
        print_sample(data, decoder.ready(), 1);
        return Ok(());
    };

    let deadline = Instant::now() + Duration::from_secs(seconds);
    let mut samples = 0u64;
    let mut freshness = StaleImuTracker::default();
    let mut errors = 0u64;
    while Instant::now() < deadline {
        match read_once(&mut protocol, serial.as_mut(), &mut decoder) {
            Ok((raw, data)) => {
                samples += 1;
                freshness.observe(&raw);
                if samples == 1 || samples.is_multiple_of(25) {
                    print_sample(data, decoder.ready(), samples);
                }
            }
            Err(error) => {
                errors += 1;
                eprintln!("IMU read error {errors}: {error}");
            }
        }
        std::thread::sleep(Duration::from_millis(20));
    }

    println!(
        "watch complete: samples={samples}, errors={errors}, stale_imu={}, max_stale_run={}, imu_ready={}",
        freshness.stale().total,
        freshness.max_run(),
        decoder.ready()
    );
    if errors > 0 {
        return Err(format!("IMU 连续读取出现 {errors} 次错误").into());
    }
    if !decoder.ready() {
        return Err("IMU 没有在观察窗口内产生 25 个有效融合样本".into());
    }
    if freshness.frozen() {
        return Err(format!("IMU 数据连续重复 {} 帧，判定冻结", freshness.max_run()).into());
    }
    Ok(())
}
