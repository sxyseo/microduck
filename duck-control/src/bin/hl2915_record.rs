use std::error::Error;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use duck_control::hl2915::Hl2915Bus;

fn usage() {
    eprintln!(
        "用法:\n  cargo run -p duck-control --bin hl2915_record -- <串口> <舵机ID...> --seconds 秒 --output 文件.csv [--hz 频率]\n\n\
只读记录 HL-2915 的位置、速度、负载、故障状态、运动标志、电流、电压和温度。\n\
不会写 ID、不会开扭矩、不会移动舵机。\n\
示例:\n  ... COM3 1 2 --seconds 600 --output bench.csv --hz 50"
    );
}

fn parse_u8(value: &str, label: &str) -> Result<u8, Box<dyn Error>> {
    value
        .parse::<u8>()
        .map_err(|_| format!("{label} 必须是 0..255 的整数：{value}").into())
}

fn parse_positive_u64(value: &str, label: &str) -> Result<u64, Box<dyn Error>> {
    let parsed = value
        .parse::<u64>()
        .map_err(|_| format!("{label} 必须是正整数：{value}"))?;
    if parsed == 0 {
        return Err(format!("{label} 必须大于 0").into());
    }
    Ok(parsed)
}

fn parse_hz(value: &str) -> Result<f64, Box<dyn Error>> {
    let hz = value
        .parse::<f64>()
        .map_err(|_| format!("频率必须是数字：{value}"))?;
    if !hz.is_finite() || !(1.0..=200.0).contains(&hz) {
        return Err("频率必须在 1..=200 Hz 之间".into());
    }
    Ok(hz)
}

fn unix_ms() -> Result<u128, Box<dyn Error>> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())
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
    let mut seconds = None;
    let mut output = None;
    let mut hz = 50.0;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--seconds" => {
                let value = args.next().ok_or("--seconds 后缺少秒数")?;
                seconds = Some(parse_positive_u64(&value, "秒数")?);
            }
            "--output" => {
                output = Some(args.next().ok_or("--output 后缺少 CSV 文件路径")?);
            }
            "--hz" => {
                let value = args.next().ok_or("--hz 后缺少频率")?;
                hz = parse_hz(&value)?;
            }
            value => ids.push(parse_u8(value, "舵机 ID")?),
        }
    }
    if ids.is_empty() {
        return Err("至少指定一个舵机 ID".into());
    }
    let seconds = seconds.ok_or("必须指定 --seconds")?;
    let output = output.ok_or("必须指定 --output")?;
    duck_control::hl2915::validate_ids(&ids).map_err(|error| error.to_string())?;

    let mut bus = Hl2915Bus::open(&port, &ids, Duration::from_millis(100))?;
    let found = bus.ping_all()?;
    if found.len() != ids.len() {
        return Err(format!("舵机响应不完整：请求 {ids:?}，响应 {found:?}").into());
    }

    let file = File::create(&output)?;
    let mut csv = BufWriter::new(file);
    writeln!(
        csv,
        "unix_ms,elapsed_ms,sample,id,position_raw,speed_raw,load_raw,status,moving,current_raw,current_ma,voltage_v,temperature_c"
    )?;
    csv.flush()?;

    let period = Duration::from_secs_f64(1.0 / hz);
    let started = Instant::now();
    let deadline = started + Duration::from_secs(seconds);
    let mut sample = 0u64;
    let mut errors = 0u64;
    while Instant::now() < deadline {
        let cycle = Instant::now();
        match bus.read_states() {
            Ok(states) => {
                sample += 1;
                let now = unix_ms()?;
                let elapsed_ms = cycle.duration_since(started).as_millis();
                for (id, state) in ids.iter().zip(states) {
                    writeln!(
                        csv,
                        "{now},{elapsed_ms},{sample},{id},{},{},{},{},{},{},{},{:.3},{}",
                        state.position_raw,
                        state.speed_raw,
                        state.load_raw,
                        state.status.unwrap_or_default(),
                        state.moving.unwrap_or_default(),
                        state.current_raw.unwrap_or_default(),
                        state.current_ma.unwrap_or_default(),
                        state.voltage_v,
                        state.temperature_c
                    )?;
                }
                if sample == 1 || sample.is_multiple_of(hz.round() as u64) {
                    println!(
                        "sample={sample}, elapsed_ms={elapsed_ms}, rows={}, output={output}",
                        sample * ids.len() as u64
                    );
                }
            }
            Err(error) => {
                errors += 1;
                eprintln!("read error {errors}: {error}");
            }
        }
        csv.flush()?;
        let remaining = period.saturating_sub(cycle.elapsed());
        std::thread::sleep(remaining);
    }
    csv.flush()?;

    println!(
        "record complete: samples={sample}, rows={}, errors={errors}, output={output}",
        sample * ids.len() as u64
    );
    if sample == 0 {
        return Err("没有记录到任何有效样本".into());
    }
    if errors > 0 {
        return Err(format!("记录期间出现 {errors} 次通信错误").into());
    }
    Ok(())
}
