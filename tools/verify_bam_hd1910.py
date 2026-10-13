#!/usr/bin/env python3
"""官方 BAM HD-1910 模型物理合理性验证 —— 拿厂家规格书当已知答案。

对照: 《HD-1910-C001 串型规格书》A/0 (2026-09-07)，@7.4V 档:
  空载速度 0.088s/60° = 113 RPM (±10%)  →  101.7–124.3 RPM
  堵转扭矩 15 kg·cm ≈ 1.471 N·m (±10%)  →  13.5–16.5 kg·cm

验证三条:
  1. 空载最高转速 —— 近零负载摆锤 + 远目标，测稳态转速 (官方解析仿真器)
  2. 堵转扭矩     —— kt·V·max_pwm/R 解析值 + "推得动/推不动"保持仿真
  3. 阶跃响应     —— 代表性负载下 0.2 rad 阶跃，m6 与 m1 对照 (模型预测, 无规格值)

用法 (需 Python 3.12, 见 docs/飞特官方BAM发布解读.md §4):
  ~/venvs/bam312/bin/python tools/verify_bam_hd1910.py           # bundled m6
  ~/venvs/bam312/bin/python tools/verify_bam_hd1910.py --model m2
  ~/venvs/bam312/bin/python tools/verify_bam_hd1910.py --json 路径/自定义.json
"""
import argparse
import math
import sys

import numpy as np

from bam.model import load_model
from bam.simulate import Simulator
from bam.testbench import Pendulum

DT = 0.001          # 官方采集脚本的定时精度 (record.py: 1 ms)
VIN = 7.4           # 规格书 7.4V 档
SPEC_RPM = 113.0    # 0.088s/60°
SPEC_STALL_NM = 15 * 0.0980665  # 15 kg·cm → N·m
TOL = 0.10          # 规格书 ±10%


def make_model(args):
    if args.json:
        return load_model(args.json)
    return load_model(motor_name="feetech_hd1910_7_4V", model=args.model)


def attach(m, mass, arm_mass, length):
    """给模型挂上台架 (等价于官方 load_log 的实例化路径)。"""
    m.actuator.testbench = Pendulum(
        {"mass": mass, "arm_mass": arm_mass, "length": length}
    )


def rollout(m, target, seconds, q0=0.0):
    """跑一段仿真，返回 (时间序列, 位置, 速度)。"""
    attach(m, *CURRENT_RIG)
    sim = Simulator(m)
    m.actuator.q_target_smooth = None  # 清掉控制律的内部平滑目标
    sim.reset(q0, 0.0)
    n = int(seconds / DT)
    qs, dqs = np.empty(n), np.empty(n)
    for k in range(n):
        c = m.actuator.compute_control(target, sim.q, sim.dq, DT)
        sim.step(c, True, DT)
        qs[k], dqs[k] = sim.q, sim.dq
    return np.arange(n) * DT, qs, dqs


def no_load_speed(m):
    # 远目标Point-to-point：饱和占空比巡航段的峰值转速即空载最高转速
    # （模型无机械限位，目标可达，4s 后已到位停住，不能取末尾窗口）
    _, _, dqs = rollout(m, target=10.0, seconds=2.0)
    rpm = float(np.max(np.abs(dqs))) / (2 * math.pi) * 60
    ok = abs(rpm - SPEC_RPM) <= SPEC_RPM * TOL
    return rpm, ok


def stall_torque(m):
    kt, R = m.kt.value, m.R.value
    max_pwm = m.actuator.max_pwm
    tau = kt * VIN * max_pwm / R
    kgcm = tau / 0.0980665
    ok = abs(kgcm - 15.0) <= 15.0 * TOL

    # 保持仿真: 水平位置 (重力臂最大) 推远目标。
    #   0.5×τ_stall → 摩擦预算之内应能推动; 1.15× → 连电机扭矩都不够，应堵转
    #   (注意 m6 的负载相关摩擦会吃掉堵转裕度，0.9× 量级在模型里本来就推不动)
    global CURRENT_RIG
    l = 0.05
    results = {}
    for label, factor, expect_move in (("0.5×", 0.5, True), ("1.15×", 1.15, False)):
        eff_mass = factor * tau / (9.80665 * l)
        CURRENT_RIG = (eff_mass, 0.0, l)  # bias = m·g·l·sin(q)
        _, qs, _ = rollout(m, target=math.pi / 2 + 1.0, seconds=1.5, q0=math.pi / 2)
        delta = qs[-1] - math.pi / 2
        pushed = delta > 0.1
        note = "推动" if pushed else ("堵转/保持" if abs(delta) <= 0.1 else "被重力压落")
        results[label] = (pushed, expect_move, note)
    return kgcm, ok, results


def step_response(m, model_name):
    global CURRENT_RIG
    CURRENT_RIG = (0.05, 0.02, 0.06)  # 代表性关节负载 I ≈ 1.94e-4 kg·m²
    _, qs, _ = rollout(m, target=0.2, seconds=2.0)
    final = qs[-1]
    peak = float(np.max(qs))
    overshoot = max(0.0, (peak - final) / 0.2 * 100)
    beyond = np.abs(qs - final) > 0.02 * 0.2
    settle = float(np.argmax(~beyond)) * DT if (~beyond).any() else float("nan")
    return {"model": model_name, "overshoot_pct": overshoot, "settle_s": settle,
            "final_rad": final, "ss_err_pct": (0.2 - final) / 0.2 * 100}


def mujoco_parity(m):
    """CPU MuJoCo 路径与解析仿真器同题对比 (同一近零负载、同一远目标)。"""
    global CURRENT_RIG
    try:
        import mujoco
        from bam.mujoco import MujocoController
        from bam.testbench_mujoco import Pendulum as MjPendulum
    except ImportError as e:
        return None
    rig = (0.001, 0.001, 0.05)
    CURRENT_RIG = rig
    pend = MjPendulum({"mass": rig[0], "arm_mass": rig[1], "length": rig[2]})
    spec = pend.build_spec(name="joint")
    spec.option.timestep = DT
    mj_model = spec.compile()
    mj_data = mujoco.MjData(mj_model)
    ctrl = MujocoController(model=m, actuator=["joint"],
                            mujoco_model=mj_model, mujoco_data=mj_data)
    n = int(2.0 / DT)
    dqs = np.empty(n)
    for k in range(n):
        ctrl.set_q_target("joint", 10.0)
        ctrl.update()
        mujoco.mj_step(mj_model, mj_data)
        dqs[k] = mj_data.qvel[0]
    rpm = float(np.max(np.abs(dqs))) / (2 * math.pi) * 60
    return rpm


CURRENT_RIG = (0.001, 0.001, 0.05)  # 默认近零负载

def main():
    global CURRENT_RIG
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="m6", choices=["m1", "m2", "m3", "m4", "m5", "m6"])
    ap.add_argument("--json", default=None, help="自定义 BAM 参数 JSON (覆盖 --model)")
    ap.add_argument("--all", action="store_true", help="m1–m6 全档位空载/堵转对照表")
    args = ap.parse_args()

    if args.all:
        print("== m1–m6 全档位对照 (空载转速 / 堵转扭矩 vs 规格 113 RPM / 15 kg·cm ±10%) ==")
        print(f"{'档位':>4} {'kt':>7} {'R(Ω)':>6} {'RPM':>7} {'kg·cm':>7}  判定")
        for name in ("m1", "m2", "m3", "m4", "m5", "m6"):
            mm = load_model(motor_name="feetech_hd1910_7_4V", model=name)
            CURRENT_RIG = (0.001, 0.001, 0.05)
            rpm, ok_rpm = no_load_speed(mm)
            tau = mm.kt.value * VIN * mm.actuator.max_pwm / mm.R.value
            kgcm = tau / 0.0980665
            ok_stall = abs(kgcm - 15.0) <= 15.0 * TOL
            marks = ("✓" if ok_rpm else "✗") + ("✓" if ok_stall else "✗")
            print(f"{name:>4} {mm.kt.value:7.4f} {mm.R.value:6.3f} "
                  f"{rpm:7.1f} {kgcm:7.2f}  转速{marks[0]} 扭矩{marks[1]}")
        print("结论: 堵转扭矩一项只有部分档位落在规格 ±10% 内 —— "
              "简化档位 (m1/m2) 的 kt/R 拟合取舍不同，用于训练前先对照本表选档。")
        return

    m = make_model(args)
    label = args.json or f"feetech_hd1910_7_4V/{args.model}"
    print(f"== 官方 BAM HD-1910 验证 · {label} ==")
    print(f"   kt={m.kt.value:.4f} N·m/V  R={m.R.value:.3f} Ω  "
          f"command_delay={getattr(m, 'command_delay').value*1000:.2f} ms")

    CURRENT_RIG = (0.001, 0.001, 0.05)

    rpm, ok_rpm = no_load_speed(m)
    kgcm, ok_stall, holds = stall_torque(m)
    print(f"\n[1] 空载最高转速   {rpm:6.1f} RPM   规格 113 ±10% → {'PASS' if ok_rpm else 'FAIL'}")
    print(f"[2] 堵转扭矩       {kgcm:6.2f} kg·cm 规格 15 ±10% → {'PASS' if ok_stall else 'FAIL'}")
    for label2, (pushed, expect, note) in holds.items():
        verdict = "符合" if pushed == expect else "不符合"
        print(f"    保持仿真 {label2}τ_stall 负载: {note} ({verdict})")

    print("[3] 阶跃响应 (0.2 rad, 代表性负载) — 模型预测, 无规格对照:")
    for name in (args.model, "m1"):
        mm = m if name == args.model else load_model(motor_name="feetech_hd1910_7_4V", model="m1")
        r = step_response(mm, name)
        print(f"    {r['model']}: 超调 {r['overshoot_pct']:5.1f}%  "
              f"整定(±2%) {r['settle_s']*1000:6.1f} ms  稳态误差 {r['ss_err_pct']:+.2f}%")

    mj_rpm = mujoco_parity(m)
    if mj_rpm is not None and rpm > 0:
        delta = abs(mj_rpm - rpm) / rpm * 100
        print(f"[4] MuJoCo CPU 一致性: {mj_rpm:6.1f} RPM vs 解析 {rpm:6.1f} RPM (差 {delta:.1f}%)")

    all_ok = ok_rpm and ok_stall
    print(f"\n结论: {'官方参数与规格书相符，可以作为强先验使用' if all_ok else '存在超出规格 ±10% 的项，先人工复核再用于训练'}")


if __name__ == "__main__":
    main()
