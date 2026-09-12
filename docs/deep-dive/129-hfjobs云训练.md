# 解读 129 · hf_jobs.py:云训练入口

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/hf_jobs.py`(483 行)
> **需要的前置**:[解读 32](32-导出与回放.md)(导出与部署)、[解读 70](70-辨识与重训.md)(重训全链路)

## 在做什么

本地没有 GPU 也能训练:`train <任务名> ... --hf-jobs` 会把整个训练搬到 Hugging Face Jobs 的云容器里跑。真正被调用的是本文件的 `submit()`(hf_jobs.py:241)——`--hf-jobs` 参数由 `train_hook.py` 拦截转发到这里;而容器内的环境变量 `MICRODUCK_IN_HF_JOB=1`(:324)会把拦截 disarm 掉,保证云上的 `uv run train` 只在本地训练,不会递归再提交一个云任务。

三个默认值定下一个"标准训练舱":镜像 `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime`(:41)、硬件 `l4x1`(:42)、超时 12 小时(:43),分别可被 `--image/--flavor/--timeout` 覆盖。

## 提交流程与 BOOTSTRAP 脚本

`submit()` 的流程是:打 tar 包 → 上传 → 提交 → 盯到结束。开头先由 `_pick_namespace()`(:171)确定命名空间(个人账号或 org;`--namespace` 跳过交互提示,非 tty 环境回落个人账号)。

1. `_build_tarball()`(:151)用 `git ls-files -co --exclude-standard` 列文件:已跟踪但未提交的修改也进包,被 ignore 的垃圾(`.venv`、logs、`*.onnx`)不进;返回短 SHA 供追溯。
2. tar 上传到私有 HF dataset 仓库(默认 `<namespace>/mjlab-microduck-src`,:318),容器里只读挂载到 `/src`(:347)。
3. `api.run_job(...)` 执行内嵌 shell 脚本 `BOOTSTRAP`(:47):装基础工具、装**钉死版本**的 uv 0.11.30(浮动 latest 读到旧版缓存条目曾让 sync 必现失败,2026-07-21)、`UV_LINK_MODE=copy`;`uv sync` 失败就清缓存自愈重试一次;然后 `nohup` 拉起 checkpoint 上传看护 `scripts/hf/uploader.py`,跑训练;训练正常结束且 `AUTO_EXPORT=1`(默认开)时**顺手导出 ONNX 并上传**(:96-118)——省得再开一个要付全额 bootstrap 的导出任务。
4. `_await_scheduling()`(:214)以 1200 秒预算轮询调度阶段(镜像拉取冷启动约 5 分钟;卷挂载失败约 7 分钟才暴露),末尾再循环跟日志;Ctrl-C 只是脱离,任务继续跑(:481-483)。调度期"卷挂载失败"是已知偶发,自动重提、最多 3 次(:402)。

## --dry-run、费用与 Token 卫生

- **--dry-run**(:267):照样打 tar 包(顺带报出大小与 HEAD SHA),然后打印将要提交的完整任务规格就返回,不花一分钱——省冤枉钱的第一道闸。
- **费用**:算力按 HF 账户 credits 扣。余额不足时 API 报 402,`submit()` 译成人话并附充值链接、退出码 2(:419-427);403 则是 token 权限问题,提示去开 fine-grained token 的 Jobs 权限、退出码 3(:428-443)。`--uv-cache` 默认关:FUSE bucket 挂载不支持硬链接,跨网络全量拷约 6 GB,反而比数据中心从 PyPI 重新下载(约 1 分钟)更慢——注释把这笔账算给你看(:286-295)。
- **Token 卫生**:HF token 只经 `get_token()`(:310)取出、放进 `secrets` 字典(:328)注入容器,不进普通 env;`--dry-run` 打印时 secrets 一律打成 `***`(:377)。wandb key 走 `_wandb_api_key()`(:124):先查 `WANDB_API_KEY` 环境变量,再翻 `~/.netrc` 的 api.wandb.ai 条目;找不到就报错退出(:333-339),而不是带病上线。

## 你带走的收获

- 云训练脚本的核心资产是那份可复现的 BOOTSTRAP:钉死工具链版本 + 自愈式依赖安装 + 训练后顺手导出,把"环境漂移"这类最常见死法提前焊死。
- `--dry-run` 是云任务脚本的第一公民:构建产物、打印规格、不调计费 API。
- 402(欠费)与 403(token 权限)是两种病,要翻译成各自的药方与退出码,脚本才能进 CI。
- git worktree 意识:`_repo_root()` 从 cwd 解析而非脚本位置(:141-148),在哪个 worktree 训练就快照哪个。

## 延伸

- 拦截入口:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/train_hook.py`;看护上传:`scripts/hf/uploader.py`
- 训练产物怎么变成部署件:[解读 32](32-导出与回放.md)
- 本文件:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/hf_jobs.py`
