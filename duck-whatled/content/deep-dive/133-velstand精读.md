# 解读 133 · velstand 配置精读

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/microduck_velstand_env_cfg.py`(416 行)
> **需要的前置**:[解读 131](131-velocity奖励表.md)(walk 层)、[解读 27](27-起身课程.md)(起身奖励)

## 一层走路 + 一层恢复

velstand = "走路 + 跌倒恢复"单策略任务(注册名 `Mjlab-VelStand-Flat-MicroDuck`,另有 Rough 版)。2026-07 重构后的结构极清晰:`make_microduck_velstand_env_cfg()`(:162)第一行就整个拿过 velocity 环(:164)——走路层零改动;然后换上能躺平的全碰撞机器人 `MICRODUCK_STANDUP_ROBOT_CFG`(:173),再叠一个小而讲究的恢复层。旧版的问题写在模块 docstring 里:2/3 趴姿重置 + 恢复奖励全程收税,只有约 25% 经验是干净走路。

关键设计是**门控**:恢复奖励只在真摔了时出钱——`REWARD_GATE_TILT_DEG=40.0`(:107)。注释里的教训:门控若带高度条件,坐姿(z≈0.07)也会开门,策略学会坐下刷 `upright_linear`、抖腿刷 air_time;只按倾角开门,舒服姿势装不出来。

## 恢复层的经济学

- 两个**基于势函数**的稠密项:`upright_progress`(权重 5.0,Δcos 倾角,:198-204)与 `height_progress`(权重 30.0,ceiling 0.115,:211-218)——上升付钱、下落扣钱、原地不动为零,刷不了。
- 两个**定时生效**的经济项:税 `fallen_tax`(课程在 1200 迭代从 0 压到 -0.5,:345-354;带滞回,倾角 <25° 且 z>0.09 才解税)与赏金 `recovery_success`(同期 0→+10,:355-364;要求倒地 ≥0.5 s 后真的站到完成定义上)。
- 阈值全部对齐实测:`RECOVERED_UP_Z=0.09`(:125)落在策略真实站立包络 0.084–0.096 内——旧的 0.105 永远够不着,赏金从不触发,恢复停在 40° 门外的深蹲(Run-5 教训);`TERM_GATE_Z=0.08`(:112)既要接住坐姿又不能误杀正常晃动。失败回收 `fallen_too_long`:连续倒地 8 秒终止(:141,:307-315)。反抖动用 standup 验证过的 `joint_torque_rate_l2`(-2e-3,:239-242);air_time 换成 `feet_air_time_upright`——倒地时腿再怎么抖也刷不了(:249-253)。

## 课程编排(Run 1–7 的沉积)

`fell_over_disable`(:321-332)在 500 迭代(`FELL_OVER_DISABLE_ITER`,:96)把 `fell_over` 阈值 70°→180°——摔倒从"episode 结束"变成"训练机会"。`prone_init_prob`(:335-341,驱动 `PRONE_RAMP_STAGES`,:153-159)按 800/1500/2000/2500 迭代爬坡:趴概率封顶 45%(保住 ≥55% 走路数据),脸朝下先行、朝上后混,另有 15% 的 `crouch_prob` 直接重置进半蹲——给"最后一英里"喂稠密数据(Run-6 验证有效)。经济项统一在 1200 迭代开闸(`RECOVERY_ECON_KICKIN_ITER`,:135):Run-6 试过 800,免税探索窗口被删,趴姿恢复率掉到 0%——**时机又一次比数值重要**。

## 你带走的收获

- 复用成熟环境做加法比重写安全:walk 层的奖励/DR/观测"按构造继承",不会漏。
- 正奖励必须门控在"不爽的状态"上,且只门在无法假装的判据上(倾角,而不是高度)。
- 税与赏金共享同一个"完成"定义并加滞回——把恢复从"可持续刷分"变成"一次性事件"。
- 阈值要贴着实测包络放:赏金线高于策略能力 = 永不触发 = 白写。

## 延伸

- 走路层的奖励与课程:[解读 131](131-velocity奖励表.md)、[解读 132](132-velocity课程.md)
- 纯起身专家版:[解读 27](27-起身课程.md)
- 本文件:`.../tasks/microduck_velstand_env_cfg.py`
