# 解读 127 · microduck_constants.py 逐段

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/robot/microduck_constants.py`(275 行,全读,无函数只有常量与配置对象)
> **需要的前置**:[解读 79](79-参数适配五落点.md)(换舵机时这个文件要动哪五处)、[解读 57](57-辨识进仿真.md)(BAM 参数怎么进仿真)

训练侧的"机器人身份证"全在这一个文件:用哪个 XML、出生摆什么姿势、装什么执行器。逐段读。

## 第一段:模型目录与开机自检(14-44 行)

八个 XML 路径常量:`MICRODUCK_WALK_XML`(行走碰撞集)、`MICRODUCK_GROUNDCONTACT_XML`(注释说明它是**精选**地面碰撞集——只有脚底、腿、躯干壳、头壳、下颌、电池等真会着地的部件,前身名字才叫 "allcollisions")、`MICRODUCK_ALLCOLLISIONS_XML`(真全碰撞:70 geom、37 mesh,"还没有任务用它",2026-09 导出备用)、ball、rollers 与三个 backlash 变体(31-35 行,每个舵机关节串一个 ±1° 齿隙被动铰,由 `add_backlash.py` 后处理生成)。37-44 行跟八个 `assert ...exists()`:文件在 **import 时**就要齐,缺一个当场崩——比训练半路才发现强得多。

## 第二段:spec 工厂与 HOME 姿势(47-109 行)

`get_walk_spec()` 等九个函数各自 `mujoco.MjSpec.from_file` 返回模型对象,任务配置经 `spec_fn=` 引用。`get_walk_rollers_spec` 里留着一条事故注释(60-62 行):曾误加载无轮模型,roller 环境**静默地**跑在错误机器人上。`HOME_FRAME`(85-109 行)是 `EntityCfg.InitialStateCfg`(出生姿势配置),键为关节名正则、值为弧度:hip_pitch -0.4579、ankle 0.4530、knee -0.0049、hip_roll ±0.0873、颈/头俯仰 0.3491。注释交代这是 STAND2 姿势:躯干前移约 5 mm 让质心压在踝轴上(旧 HOME 质心偏后,standup 策略被迫用点头当配重),与 scene.xml 的 STAND keyframe 一致。

## 第三段:碰撞与执行器 kwargs(111-158 行)

`FULL_COLLISION`(111-116 行)一条规则集:脚底碰撞 condim=3(三维接触,带摩擦锥)、摩擦 1.0、优先级 1,其余 geom condim=1。执行器段先留着两段注释掉的旧方案(XML 位置执行器 + 延迟、BAM M4),现行的是 `_BAM_ACTUATOR_KWARGS`(132-144 行):`motor_name="xl330"`、`model="m6"`、`target_names_expr=(r"^(?!passive_).*",)`(负向正则排除全部被动关节)、`kp_fw=200.0`(注释:microduck 保留的固件刚度,microban 用 125)、`vin_range=(6.5, 8.2)`(电池电压随机化窗口)、`vin_drop_gain_range=(0.0, 0.2)`(负载压降系数)、`vin_min=6.0`、`delay_min_lag/delay_max_lag=3/6`(动作延迟 3–6 拍)。这份 dict 被两份配置共用:`actuators = FrictionDRBamActuatorCfg(**...)`(145 行)与 `backlash_actuators = BacklashEncoderBamActuatorCfg(**...)`(151 行,固件位置环改读**穿过齿隙**的编码器,只配齿隙模型)。

## 第四段:配置表与"首匹配获胜"技巧(166-262 行)

六个 `EntityCfg`(机器人整体配置对象)各由 `spec_fn + init_state + collisions + actuators` 拼成,全部 `soft_joint_pos_limit_factor=0.9`(软限位收到硬限位九成,留缓冲)。WALK/STANDUP/GROUND_PICK 共用 groundcontact 模型;BACKLASH 三兄弟用 `BACKLASH_HOME_FRAME`(166-169 行),这里有个正则细节值得抄:HOME_FRAME 的 `.*left_hip_roll.*` 会连 `passive_left_hip_roll_backlash` 一起匹配,把 ±1° 的齿隙铰初始化到 -0.0873 rad 直接超程——解法是利用 dict 声明顺序的"首匹配获胜",把 `r".*_backlash$": 0.0` 放最前钉死齿隙铰,舵机键自然落空到后面的正常值。BALL 配置(244-247 行)是个自由浮球,初始位置 (0.3, 0, 0.035) 只管首次重置前;末尾 264-275 行的 `__main__` 块把 WALK 配置装进场景直开 viewer——`python microduck_constants.py` 即目检。

## 你带走的收获

- 资源路径在 import 时 assert,把"找不到文件"从运行时错误提前到加载错误。
- 出生姿势不是拍脑袋:质心对踝轴的 5 mm 挪动背后是一次头前倾代偿的修复。
- 共享 kwargs dict 让两代执行器配置永远不漂移;`^(?!passive_).*` 一个负向正则守住 14 维动作空间。
- 带正则键的姿势表要防"误伤":首匹配获胜的声明顺序就是作用域控制。

## 延伸

- 换舵机时本文件的五个改动点:[解读 79](79-参数适配五落点.md);电压窗口的含义:[解读 87](87-代码里的电压.md)
- 齿隙模型与观测:[解读 31](31-对称与齿隙.md)、[解读 123](123-mdp二观测函数.md)
- 本地路径:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/robot/microduck_constants.py`
