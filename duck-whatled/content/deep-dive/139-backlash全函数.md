# 解读 139 · backlash.py 全函数

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/backlash.py`(92 行,全读:1 个常量 + 1 个函数)
> **需要的前置**:[解读 31](31-对称与齿隙.md)(导览:齿隙建模的动机)、[解读 21](21-任务注册表.md)(15 个 Backlash 任务怎么注册)

导览(31 篇)讲了它做什么:一键把环境配置换成"每个伺服关节串联一个 ±1° 被动齿隙铰链"的模型,维度一字不动。本篇走完 `make_backlash_variant` 的四段改写,重点在两处正则修缮和一个 deepcopy。这个 92 行文件里藏着三个"改别人配置之前必须想清楚"的通用教训。

## 第一段:换机器人(39-47 行)

`_SERVO_JOINTS_ONLY = (r"^(?!passive_).*",)`(:39)是全文的枢纽:一个负向前瞻正则,匹配所有**不以** `passive_` 开头的关节。可行性靠 docstring(:23-26)点明的命名纪律:齿隙铰链一律叫 `passive_<joint>_backlash`,环境里既有的 `^(?!passive_).*` 选择器(执行器、奖励、观测)天然排除它们,零改动。`make_backlash_variant(cfg, robot_cfg=MICRODUCK_BACKLASH_ROBOT_CFG)`(:42-46)的第一行(:47)用字典重建把 `"robot"` 换成齿隙模型。默认参数按族各不同:Velocity 传 `MICRODUCK_WALK_BACKLASH_ROBOT_CFG`,VelStand/StandUp 用默认 groundcontact 版——基础任务用什么碰撞模型,齿隙版就镜像什么(docstring :11-14)。

## 第二段:换观测函数(49-64 行)

`for group in ("actor", "critic")` 双循环(:49),把 `joint_pos`/`joint_vel` 两项的 func 换成 `joint_pos_rel_backlash`/`joint_vel_rel_backlash`(:51-58)——策略从此看到 `qpos[伺服] + qpos[齿隙]` 的"编码器视角",与真伺服(编码器装在齿轮空程输出侧)同构。两道防御:`if term is None: continue`(:56)跳过没有该项的环境;:61-64——若环境从未写 `asset_cfg`,齿隙关节会混进观测(维度错+重复计数),故补只含 `_SERVO_JOINTS_ONLY` 的 `SceneEntityCfg`。

## 第三段:两处奖励修缮(68-90 行)

`dof_pos_limits`(:68-72):齿隙关节的一生就是顶着 ±1° 硬限位——这是它的本职,但软限位惩罚的默认选择器覆盖所有关节,会把恒定的越界惩罚灌进奖励。同样只在环境没写过 `asset_cfg` 时才补。`pose` 奖励(:81-90)更隐蔽:它按选中关节名查 std 字典,歧义匹配直接**报错**(注释 :74-79)——齿隙模型里 `passive_left_hip_yaw_backlash` 会同时撞上 `.*hip_yaw.*` 和 roller 环境的 `.*passive_.*` 两条 std。修法是把选择正则逐条前置一段排除:`p if "_backlash" in p else r"^(?!passive_.*_backlash)" + p.lstrip("^")`(:87-89),与已有前瞻(velocity 的 passive/neck/head 排除)叠加组合。

而 :84-86 是全文件最重要的一行注释:"base templates share SceneEntityCfg objects across make() calls; mutating in place would leak into the base tasks"——配置工厂的产物不是深拷贝,同一个 `SceneEntityCfg` 对象会被多次 `make()` 共享,所以先 `deepcopy` 再改,否则**非齿隙的基础任务会被齿隙版污染**。

## 消费方:一个循环注册 15 个变体(交叉 tasks/__init__.py:240-278)

backlash.py 自己不注册任何任务。`tasks/__init__.py` 用一张 `_BACKLASH_TASKS` 表(:253-268)把 15 个变体(velocity/velstand/standup/sitstand/groundpick/ball_kick 各 Flat+Rough、rollers/swizzle/roller_crouch/roller_slope 各一个)交给一个 for 循环,每个都调 `make_backlash_variant(make_cfg(...), robot_cfg)` 生成 env 与 play_env 两份,任务 id 按约定插段:`Mjlab-Velocity-Flat-Backlash-MicroDuck`。12 行改造 + 注册表一行循环撑起 15 个任务——这就是借道命名约定的杠杆。

## 你带走的收获

- 给仿真加机械缺陷时,用命名前缀划出"新关节"边界,让存量正则自动排除它们,改造面趋近于零。
- 改共享配置对象前先 deepcopy:工厂函数之间共享的不只是值,是对象身份;原地改会泄漏回基础任务。
- 奖励项的关节选择正则会因新增关节产生歧义匹配,而且有的实现是静默错、有的是直接报错——换模型后要逐项过 `asset_cfg`。
- 维度不变是设计红线:obs/动作仍 14 维,运行时与导出链零改动。

## 延伸

- 齿隙的物理与执行器侧(BacklashEncoderBamActuator):[解读 31](31-对称与齿隙.md)、[解读 54](54-BAM是什么.md)
- 这些变体对策略的影响:[解读 81](81-策略影响评估.md);导出链路为何不受影响:[解读 128](128-export全函数.md)
- 本地路径:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/backlash.py`
