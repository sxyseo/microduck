# 解读 140 · play_latest.py

> **解读对象**:`microduck-replica/upstream/microduck_rl/scripts/play_latest.py`(57 行,全读:1 个字典 + 1 个 main)
> **需要的前置**:[解读 129](129-hfjobs云训练.md)(wandb run 从哪来)、[解读 130](130-infer主流程.md)(`uv run play` 消费什么)

这是 scripts/ 目录里最短的文件,却回答一个每天都会遇到的问题:"我昨天训了一晚上,现在怎么把它放出来看?" 手工做法要查 task id、翻 wandb 复制 run path、拼一长串命令;`play_latest.py` 把这串摩擦压成 `md-play --crouch`。连文件头 docstring(:1-11)都是法语写的,默认用户 `coralie` 是它的第一位使用者。

## TYPE_SUBSTR:四个 flag 与子串匹配的陷阱(18-23 行)

类型路由是一张字典:`crouch → "Crouch"`、`roller → "MicroDuck-Rollers"`、`swizzle → "Swizzle"`、`slope → "Slope"`,注释逐行给出对应 task id 示例。最讲究的是 roller 这条:子串故意用 `"MicroDuck-Rollers"` 而不是 `"Roller"`——注释(:20)点明 `Mjlab-Velocity-Flat-MicroDuck-Rollers` 与 `RollerSlope`/`RollerCrouch` 共享前缀,宽子串会抓错任务族。子串匹配本身发生在 `wandb_utils.resolve_run`(wandb_utils.py:110-125)里:`task_substr.lower() in t.lower()` 大小写不敏感地过滤该用户的 run,取最新一条;一个都没有就打印 stderr 并 `sys.exit(1)`。这个脚本没有自己的业务逻辑,匹配、排序、报错全部委托给 `wandb_utils`。

## main:解析、解析、拼命令(26-53 行)

三个动作按顺序读。第一,参数解析分两层:`for t in TYPE_SUBSTR` 循环注册 `--crouch/--roller/--swizzle/--slope` 四个互斥 flag(`store_const` 把选中键写进 `args.type`,:36-40);`parse_known_args()`(:42)把**不认识**的参数(如 `--action-scale 0.8`)收进 `extra` 原样放行——docstring(:9-10)承诺"Les arguments inconnus sont transmis tels quels"。第二,`resolve_run(args.user, task_substr)`(:45)返回 `(run, info)`,其中 `info` 是 `{"env_name", "run_path", "checkpoints"}`(wandb_utils.py:107)——env_name 和 run_path 正是下游要的两个词。第三,拼出命令(:47-52):`uv run play <env_name> --wandb-run-path <run_path> *extra`,交给 `run_command(cmd, args.dry_run)`(:53);后者(wandb_utils.py:128-138)先打印整条命令,`--dry-run` 时到此为止,否则在项目根目录 `subprocess.run` 执行。

## 设计取舍:外壳要薄到什么程度

值得学的不是这个脚本做了什么,而是它**拒绝**做什么:不 import wandb API、不解析 checkpoint、不知道 play 命令长什么样——它只做"查 + 拼 + 传"。未知参数透传(:42)让上游 `play` 的任何新 flag 无需改壳即可用;`--dry-run` 让"要跑什么"变成可先审阅的一行字。与 129 篇的 `hf_jobs`(把训练送上云)相对,这个 57 行文件是训练闭环的另一端:云端 run 落地后,人机接口被压扁成一个 flag。工程里大量工具的真实形态就是这样——不是框架,是三行胶水,但子串选 `"MicroDuck-Rollers"` 这种坑,只有踩过一次才写得出注释。

## 你带走的收获

- "跑最新一次训练"值得一个专用命令:它消灭的是每天复制 run path 的摩擦,不只是省几个键击。
- 子串匹配任务族时,边界要选得比直觉更窄(`MicroDuck-Rollers` vs `Roller`),否则前缀相近的任务会被抓错。
- `parse_known_args` + 透传是包装 CLI 的标准姿势:壳不认识的功能自动可用。
- `--dry-run` 是所有"拼命令再执行"类工具的标配安全阀。

## 延伸

- run 的另一端——训练怎么提交上云:[解读 129](129-hfjobs云训练.md);play 消费的 ONNX 怎么导出:[解读 128](128-export全函数.md)
- 各任务族本体:swizzle [解读 134](134-swizzle精读.md)、roller 家族 [解读 135](135-roller家族.md)
- 本地路径:`microduck-replica/upstream/microduck_rl/scripts/play_latest.py`、`scripts/wandb_utils.py`
