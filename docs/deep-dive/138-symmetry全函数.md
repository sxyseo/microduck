# 解读 138 · symmetry.py 全函数

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/symmetry.py`(169 行,全读:1 个 dataclass + 2 个函数)
> **需要的前置**:[解读 31](31-对称与齿隙.md)(导览:镜像对称是什么、为何可用可不用)、[解读 23](23-velocity配置中.md)(61 维观测怎么拼)

导览(31 篇)讲了"左右镜像 = 一张置换表加一张符号表"这个思想;本篇逐函数走完剩下的三层:**表是怎么生成而不抄错的、表怎么变成 GPU 上的张量、镜像函数怎么被 PPO 消费**。全文只有三个可调用对象,每一步都能对到行号。

## 四张表:组合生成,而非手抄(68-95 行)

关节级两张表:`_JOINT_PERM = [9,10,11,12,13,5,6,7,8,0,1,2,3,4]`(:68,左腿 0-4 与右腿 9-13 互换、中线 5-8 原地)与 `_JOINT_SIGN`(:71,14 个符号里只有下标 5、6 是 +1——neck_pitch 和 head_pitch 两个矢状面关节;连 head_yaw/head_roll 都要变号)。观测级两张表**不是**重抄的:`_OBS_PERM`(:74-83)用三行列表推导(如 `[6 + j for j in _JOINT_PERM]`)把同一张关节表平移进三个 14 维块——表只写一次,三处不可能抄出错。`_OBS_SIGN`(:86-95)按段拼接,每段行尾注释写物理理由:角速度取负 roll/yaw(:87)、重力投影取负 gy(:88)、twist 取负 lin_vel_y/ang_vel_z(:92)、头命令取负 yaw/roll(:93)、身体命令取负 y/roll/yaw(:94)——非关节段符号必须逐段另立。

## _get_tensors:按设备缓存的一次性搬运(98-110 行)

模块级 `_cache`(:98)是一个 `dict[device, 四元组]`。`_get_tensors`(:101)首次见到某设备时,把四张 Python 列表转成该设备上的 long/float 张量并缓存,之后 O(1) 直取。理由是热路径:镜像在每个 PPO 更新里多次被调,不缓存就得每次把 61 个索引重新搬上 GPU(注释:97 行)。它定义了这些表的运行时形态:不是列表,是 device 上的张量。

## microduck_vel_symmetry:函数契约与三行核心(118-169 行)

签名 `(env, obs, actions)` 里 `env` 未用——为兼容 rsl_rl 的 `symmetry_cfg` 接口(docstring :130);obs 与 actions 都允许 `None`,各自独立处理(:143、:164)。观测分支两行数学:`actor_sym = actor_orig[:, obs_perm] * obs_sign`(:146)——高级索引重排、广播乘法变号;再沿 batch 维拼成 `[original; mirrored]`(:157)。动作分支同理,用关节级两表(:166-167)。

critic 分支是全文件最值得读的妥协(:148-153):不镜像,只把原观测 `torch.cat` 复制一份凑 batch。注释给出的理由:镜像损失只需 actor 侧成立;critic 看的是特权信息,数据增强模式下它收到的是"未镜像的重复观测",无害近似。注意一处文档滞后:docstring 说输出键 `"policy"`(:132),实现用 `"actor"`(:144、:156)——mjlab 1.3.0 迁移后的现实,旧键会 KeyError(文件头 :6-7)。

## SYMMETRY_CFG 怎么到达 PPO(49-61 行,交叉 tasks/__init__.py)

`PpoWithSymmetryCfg`(:49)只给标准配置加一个 `symmetry_cfg: dict | None` 字段;真参数是模块级 `SYMMETRY_CFG`(:56):`use_mirror_loss=True`、`mirror_loss_coeff=0.5`、`use_data_augmentation=False`;`data_augmentation_func` 存的是**字符串路径** `"mjlab_microduck.tasks.symmetry.microduck_vel_symmetry"`(:60)而非函数对象——字符串能进 YAML、能随配置序列化。消费侧写作 `symmetry_cfg=SYMMETRY_CFG if ENABLE_SYMMETRY else None`(roller_crouch :471 等),v1.5 各环境 `ENABLE_SYMMETRY` 均为 `False`。跨文件细节在 `tasks/__init__.py:24-35` 的 `MicroduckOnPolicyRunner`:rsl_rl 会把 `_env` 注入这个 dict,而 `MjSpec` 不可 pickle,须拷贝剔除才能落盘 YAML——镜像配置引发的序列化暗坑。

## 你带走的收获

- 对称表用"一张关节表 + 偏移列表推导"组合生成,三处 14 维块天然一致;符号表必须逐段手写并注释物理理由。
- 缓存张量按 device 分桶,是训练热路径上最便宜的一类优化。
- 镜像损失只约束 actor;critic 复制不镜像是写进注释的有意近似,不是 bug。
- 配置里用字符串引用函数,换来可序列化;代价是要有人负责把字符串解析回函数。

## 延伸

- 导览与取舍(哪个环境敢开对称):[解读 31](31-对称与齿隙.md);第一个特技任务:[解读 29](29-特技任务.md)
- 61 维观测的拼装原稿:[解读 23](23-velocity配置中.md);齿隙的另一侧改造:[解读 139](139-backlash全函数.md)
- 本地路径:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/symmetry.py`
