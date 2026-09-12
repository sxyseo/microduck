# 解读 137 · testbench_env_cfg.py

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/testbench_env_cfg.py`(298 行,全读)
> **需要的前置**:[解读 60](60-testbench验证.md)(台架对照全景)、[解读 55](55-单摆台架.md)(台架物理设计)

这是把 15 关节的鸭子砍成**一颗舵机**的训练配置:单自由度、固定基座的关节跟踪任务。文件头 docstring(1-8 行)把设计立场说完——起点 0°、目标角在 ±80° 均匀采样;观测噪声与动作平滑正则照抄 velocity 环境,**但没有任何域随机化**,这样训出的策略可以直接搬到真实 XL330 台架上当"同一个策略"用。它既是训练配置,也是 142 篇 mjlab 后端直接 import 的环境工厂。

## TargetAngleCommand:一维命令怎么写成 CommandTerm(54-91 行)

velocity 环境的命令是 3 维速度指令,这里只有 1 个标量角度。`TargetAngleCommand`(54 行)继承 mjlab 的 `CommandTerm`,四个槽位分工明确:`command` property(67 行)返回内部缓存的 `_target`;`_resample_command`(71 行)按 `cfg.range` 均匀重采,没有任何偏好角度;`_update_command`(77 行)整个是 `pass`,目标在保持期内不变;`_update_metrics`(80 行)把 `|q - target|` 写进 `metrics["error"]` 供训练曲线观测。配置 `TargetAngleCommandCfg`(85 行)给出三个关键数:关节名就是字符串 `"1"`(:89,台架 XML 里唯一的铰链)、范围 `±TESTBENCH_MAX_ANGLE_RAD`(:51,`math.radians(80.0)`)、`resampling_time_range = (4.0, 4.0)`(:91)——每 4 秒换一次目标,与 142 篇的 `hold_time=4.0` 对齐。

## make_testbench_env_cfg:velocity 配方的最小化移植(121-266 行)

观测四项(126-144 行):`joint_pos_rel` 噪声 ±0.0006(与 velocity 相同),`joint_vel_rel` 噪声 ±0.24——注释(131-134 行)解释这是 velocity 环境 0.024 的 **10 倍**,因为 XL330 固件的速度读数远比 MuJoCo 的瞬时 qdot 噪;该项还带 `delay_min_lag/max_lag = 1` 的一拍延迟(:136-138)。policy 组开噪声、critic 组 `enable_corruption=False`(:163)。

动作与事件(167-202 行):`JointPositionActionCfg` 的 `scale` 从环境变量 `TESTBENCH_ACTION_SCALE` 读(170 行,默认 1.0),扫参不用改文件;`reset_joint` 事件的 `position_range/velocity_range` 都是 `(0.0, 0.0)`(:196-198),这就是 docstring 里"无域随机化"的落点。

奖励五项(205-231 行),注释自称 "same regularization recipe as the microduck velocity env":`track_target` 权重 3.0、`std = math.sqrt(0.15)`(:211,`target_angle_tracking`(99 行)算 `exp(-err²/std²)`),`dof_pos_limits` −1.0、`action_rate_l2` −0.6、`joint_torques_l2` 与 `joint_vel_l2` 各 −1e-3——与 131 篇的 velocity 表同名同量级。终止只有 `time_out`(233 行)、`curriculum={}`(250 行);每回合 8 秒(:265),0.005 × decimation 4 = 50 Hz(:262-264)——整机策略的训练节奏原样搬进台架。

## MicroduckTestbenchRlCfg:小网络与一个待验证点(269-298 行)

PPO 配置把网络砍小:`actor/critic_hidden_dims = (256, 128, 64)`、`init_noise_std = 1.0`、学习率 1e-3(`schedule="adaptive"`,`desired_kl = 0.01`)、`max_iterations = 2000`、`experiment_name = "testbench"`。注意 `actor_obs_normalization = False`(:272-274)——与 128 篇的导出归一化路径相反,这里根本不归一化,部署端也就无归一化器可忘。

一个诚实观察:`MicroduckTestbenchRlCfg` 目前**没有**出现在 `tasks/__init__.py` 的 `register_mjlab_task` 清单里;`make_testbench_env_cfg` 的现有消费方是 `scripts/testbench_sim2real.py` 的 `rollout_sim_mjlab`(:226 直接 import)。训练入口如何引用这份 RL 配置,待验证。

## 你带走的收获

- sim2real 台架任务的配方 = 真实任务的观测噪声 + 无域随机化:噪声让它扛得住真传感器的脏,零随机化让"仿真策略=实物策略"这个等式严格成立。
- 命令周期 4 s 与回放脚本 `hold_time=4.0` 是一处跨文件契约——配置侧和验证侧改哪个都要同步。
- 观测延迟(`delay_lag=1`)是独立的噪声维度:一拍延迟比噪声更能复现"固件读数慢半拍"。
- 小任务用小网络、关归一化:配置应当随问题规模缩放,而不是整体复制。

## 延伸

- 台架验证怎么消费这份配置:[解读 142](142-testbench双脚本.md);对照全景:[解读 60](60-testbench验证.md)
- 同名奖励项的 velocity 原版:[解读 131](131-velocity奖励表.md);BAM 执行器从哪来:[解读 54](54-BAM是什么.md)
- 本地路径:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/testbench_env_cfg.py`
