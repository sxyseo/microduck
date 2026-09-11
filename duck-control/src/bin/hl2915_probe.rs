use std::error::Error;
use std::time::{Duration, Instant};

use duck_control::hl2915::{Hl2915Bus, POSITION_CENTER};

fn usage() {
    eprintln!(
        "用法:\n  cargo run -p duck-control --bin hl2915_probe -- <串口> [ID ...] [选项]\n\n默认只 Ping + 读取，不会让舵机运动。\n选项:\n  --set-id 新ID       只接一只舵机时修改 ID\n  --move-center       显式回中，必须先确认机械安全\n  --watch-seconds 秒  连续只读，检查丢包/电压/温度\n示例:\n  ... COM3 1\n  ... COM3 1 --set-id 2     (总线上只能接这一只舵机)\n  ... COM3 1 2               (两只 ID 已分别设置为 1、2)\n  ... COM3 1 2 --watch-seconds 60\n  ... COM3 1 2 --move-center  (确认机械安全后才使用)"
    );
}

fn parse_u8(value: &str, name: &str) -> Result<u8, Box<dyn Error>> {
    value
        .parse::<u8>()
        .map_err(|_| format!("{name} 必须是 0..255 的整数: {value}").into())
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args().skip(1);
    let Some(first) = args.next() else {
        usage();
        return Ok(());
    };
    if first == "-h" || first == "--help" {
        usage();
        return Ok(());
    }

    let port = first;
    let mut ids = Vec::new();
    let mut set_id = None;
    let mut move_center = false;
    let mut watch_seconds = None;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--move-center" => move_center = true,
            "--set-id" => {
                let value = args.next().ok_or("--set-id 后缺少新 ID")?;
                set_id = Some(parse_u8(&value, "新 ID")?);
            }
            "--watch-seconds" => {
                let value = args.next().ok_or("--watch-seconds 后缺少秒数")?;
                let seconds = value
                    .parse::<u64>()
                    .map_err(|_| format!("秒数必须是正整数: {value}"))?;
                if seconds == 0 {
                    return Err("--watch-seconds 必须大于 0".into());
                }
                watch_seconds = Some(seconds);
            }
            value => ids.push(parse_u8(value, "舵机 ID")?),
        }
    }
    if ids.is_empty() {
        ids.push(1);
    }
    if set_id.is_some() && ids.len() != 1 {
        return Err("--set-id 必须只连接并指定一只舵机".into());
    }

    let mut bus = Hl2915Bus::open(&port, &ids, Duration::from_millis(100))?;
    let found = bus.ping_all()?;
    println!("端口 {port} @ 1Mbps；请求 ID={ids:?}；响应={found:?}");
    if found.len() != ids.len() {
        return Err("有舵机没有响应：先断电检查 GND/Vcc/Signal、ID 和半双工转接板".into());
    }

    if let Some(new_id) = set_id {
        let old_id = ids[0];
        bus.set_id(old_id, new_id)?;
        println!("已把 ID {old_id} 写成 {new_id}。断电重启后再用新 ID 测试。");
        return Ok(());
    }

    if move_center {
        println!("即将回中；请确认舵机已卸载、输出轴不会夹伤人或撞结构。");
        bus.set_torque(true)?;
        let result = (|| {
            bus.write_positions_raw(&vec![POSITION_CENTER; ids.len()])?;
            std::thread::sleep(Duration::from_secs(1));
            Ok::<_, Box<dyn Error>>(())
        })();
        let torque_off = bus.set_torque(false);
        result?;
        torque_off?;
    }

    if let Some(seconds) = watch_seconds {
        let deadline = Instant::now() + Duration::from_secs(seconds);
        let mut samples = 0u64;
        let mut errors = 0u64;
        let mut min_voltage = f32::INFINITY;
        let mut max_temperature = f32::NEG_INFINITY;
        while Instant::now() < deadline {
            match bus.read_states() {
                Ok(states) => {
                    samples += 1;
                    for state in states {
                        min_voltage = min_voltage.min(state.voltage_v);
                        max_temperature = max_temperature.max(state.temperature_c as f32);
                    }
                    if samples == 1 || samples.is_multiple_of(10) {
                        println!(
                            "watch: samples={samples}, min_voltage={min_voltage:.1}V, max_temperature={max_temperature:.0}°C"
                        );
                    }
                }
                Err(error) => {
                    errors += 1;
                    eprintln!("watch read error {errors}: {error}");
                }
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        println!(
            "watch complete: samples={samples}, errors={errors}, min_voltage={min_voltage:.1}V, max_temperature={max_temperature:.0}°C"
        );
        if errors > 0 {
            return Err(format!("连续只读期间出现 {errors} 次通信错误").into());
        }
        return Ok(());
    }

    let states = bus.read_states()?;
    for (id, state) in ids.iter().zip(states) {
        println!(
            "ID {id}: position={} ({:.2}°), speed_raw={}, load_raw={}, voltage={:.1}V, temp={}°C",
            state.position_raw,
            duck_control::hl2915::raw_to_degrees(state.position_raw),
            state.speed_raw,
            state.load_raw,
            state.voltage_v,
            state.temperature_c
        );
    }
    Ok(())
}
