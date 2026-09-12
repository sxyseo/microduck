# 解读 128 · export.py 全函数

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/export.py`(311 行,全读:3 个函数 + 2 个 dataclass)
> **需要的前置**:[解读 32](32-导出与回放.md)(导出在部署链路的位置)、[解读 03](03-策略加载.md)(机器人侧怎么消费 ONNX)

这是 checkpoint 到可部署 `.onnx` 的唯一通路。文件头 docstring(1-10 行)把立场说死:仿真内 `play` 会自己套归一化,掩盖过"手工转换却忘了归一化器"的 checkpoint——**永远别手工转**;`scripts/export.py` 只是命令行外壳,发布管线直接调 `run_export`,让发布的策略无法绕过这一步。

## 两个 dataclass:配置与回执(33-69 行)

`ExportConfig` 是 frozen dataclass(不可变配置对象,`@dataclass(frozen=True)` 一句话:实例化后字段不可再赋值):`onnx_file` 默认 "output.onnx"、`agent` 取 "zero/random/trained"(默认 trained)、`checkpoint` 按 iteration 数选、`checkpoint_file` 直接给路径、`video=False`、`video_length=200` 等;`_demo_mode` 用 `tyro.conf.Suppress` 藏出命令行。`ExportResult`(55-62 行)是导出回执:onnx 路径、checkpoint 路径、wandb run 路径、iteration——给发布器的"来源证明"块用。`_iteration_of`(65-69 行)用正则 `model_(\d+)\.pt$` 从文件名抽数字。

## run_export(上):定位 checkpoint 与 motion(72-200 行)

`DUMMY_MODE = agent in {"zero", "random"}`(80 行)把流程劈成两半。运动追踪任务的分支(84-148 行)在 dummy 模式下强制要求 `registry_name` 并从 wandb artifact 下载 `motion.npz`;训练模式下按"CLI > 配置已设 > run 的 used_artifacts"三级兜底。checkpoint 解析(150-200 行)同样三级:`checkpoint_file` 给本地路径;`checkpoint` 给 iteration 数时,若给了 `wandb_run_path` 就下载到 `logs/rsl_rl/<实验名>/wandb_checkpoints/<run_id>/`(已存在打印 cached,否则 downloaded);两者都没有时必须给 `wandb_run_path`。每条路都打印实际加载的文件名,溯源从这一刻开始。

## run_export(下):环境、假策略与真正的导出(202-277 行)

环境按 `load_env_cfg(task_id, play=True)` 建,`RslRlVecEnvWrapper` 包上 `clip_actions`(227 行)。dummy 分支现场定义两个迷你策略类:`PolicyZero` 恒输出零、`PolicyRandom` 输出 ±1 均匀随机(232-245 行)——用假策略跑通环境与录制管线,是"不训练也能验部署"的验收件。训练分支加载 `OnPolicyRunner` 并 `runner.load(resume_path)`。

真正的导出只有三行(258-267 行):`runner.export_policy_to_onnx(path, filename)`、`get_base_metadata(...)`、`attach_metadata_to_onnx(...)`。注释解释了 mjlab 1.3.0 后归一化为什么不用手动管:经验归一化 `EmpiricalNormalization` 是策略 MLPModel 的子模块(`obs_normalization=True`),导出图自动生成 `actor(normalizer(obs))`——机器人端拿到的就是训练时的口径。注意 `get_base_metadata` 正是 122 篇讲的 mdp.py 补丁 4 替换掉的函数:import mdp 后这里实际执行的是过滤 `passive_*` 关节的版本,元数据里 joint_names/stiffness/damping/default_joint_pos 与 14 维动作空间保持一致——两个文件隔着补丁暗通款曲。一个可验证的细节:三个分支都给 `policy` 赋值(237/245/250 行),此后再没被读过——导出走 runner 内建方法,赋值只为对齐分支逻辑。最后 `env.close()` 并填 `ExportResult` 回执。

## main:两段式命令行(280-307 行)

先 `tyro.cli` 用任务清单生成字面量类型让用户选任务(`add_help=False, return_unknown_args=True` 放行剩余参数),再对 `ExportConfig` 跑第二次 tyro 解析,配置 `AvoidSubcommands` 与 `FlagConversionOff`。中间 `load_rl_cfg` 后又 `del agent_cfg`——解析器借它生成参数,实际运行全靠 run_export 内部重新加载。

## 你带走的收获

- 部署件最大的坑是"训练口径 ≠ 部署口径":归一化要烘进计算图,而不是靠调用方记得。
- 唯一通路原则:发布管线直接调 `run_export`,"跳过导出"在结构上不可能。
- dummy 策略(zero/random)让导出管线没有 checkpoint 也能端到端演练。
- 元数据在导出后附着,且元数据函数可被上游模块打补丁——导出内容随任务定义联动。

## 延伸

- 导出与回放全景:[解读 32](32-导出与回放.md);metadata 补丁的来历:[解读 122](122-mdp一文件结构.md)
- ONNX 到真机:[解读 03](03-策略加载.md);七阶段路线中的位置:[解读 70](70-辨识与重训.md)
- 本地路径:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/export.py`
