# Microduck Studio

个人本地复刻工作台的持续实现。它管理项目、硬件档案、装配标定、台架测试、训练部署和证据记录；不直接写舵机、不替代 `robotd`，也不会自动选择 HL-1910 或 HL-2915。

## 集成开发工作台

当前版本把辅助开发收敛到同一个项目和运行记录中：

- 分阶段硬件：可为主控、单舵机台架、关节组、IMU、摄像头和整机记录 `planned`、`owned`、`installed`、`detected`、`verified` 或 `failed`，只解锁现有硬件能够完成的调试能力。
- 受控训练：除固定 CPU smoke 外，可使用服务端内置 `walk` 配方生成和启动本机 Linux/macOS 或 WSL2 训练；参数经过范围校验，不接受任意 Shell。
- 显式续训：必须同时选择父训练运行和该运行已登记、哈希一致的 `.pt` checkpoint；硬件、观测动作或控制频率契约不一致时不会启动。
- 可视化调试：每次运行提供增量时间线；可比较两个已结束运行的生效配置和数值指标，并用浏览器原生 SVG 显示变化。
- 项目配置：保存默认执行位置、可见指标和告警阈值；实际生效参数仍写入每次运行证据。
- 多端布局：同一网页在 PC、平板和手机上响应式排列。手机窄屏隐藏硬件运动和部署启动按钮，取消和只读查看仍保留；服务端确认仍是安全边界。

远程 GPU 目标可以登记并生成明确的“尚不可执行”结果；在远端 checkpoint 哈希和断线状态对账完成前，工作台不会把 SSH 长训练伪装成已支持。服务仍默认监听本机地址，不应直接暴露到公网。

## 运行

```powershell
cd microduck-studio
uv sync --extra test
uv run pytest -q
uv run python -m microduck_studio
```

打开 <http://127.0.0.1:8765>。数据库默认写入 `microduck-studio/studio.db`，可用 `MICRODUCK_STUDIO_DB` 指定位置。页面默认把项目根设为启动目录的上一级（`..`），对应 Microduck 仓库；若资料在其他目录，请先修改路径。

当前页面用于验证最小闭环：创建“我的鸭子”、保存待确认或已确认硬件路线、运行只读环境预检、生成/执行需确认的只读探针、导入连续测试原始计数并找回报告。探针按钮默认只生成计划；执行前会弹出确认，服务会把真实输出重新解析成结构化证据，避免采信脚本打印的 `PASS`。

连续测试、舵机探针、训练 smoke、TensorBoard 摘要、主控健康和兼容性判定结果都会保存稳定的 `rule_version`，报告可以据此区分判定规则版本；历史记录保留原规则版本，不会被新规则静默改写。连续测试还会绑定执行时的硬件档案并保存原始输入；没有已确认硬件时只能记录为证据不足，不能把舵机体检任务标成通过。原始计数或时长缺失时会标出 `missing_fields`，不会用零值代替；发送/丢包计数必须是整数，时长必须是有限数，类型不可信时保持证据不足。

环境预检还会保存只读基线：Git commit/分支/工作树是否有已跟踪改动、平台和 Python 版本，以及 Python、uv、rustc、cargo 的版本；工具不可用或目录不是 Git 仓库时记录为不可用，不会把缺失信息填成零值或误报成功。Markdown 报告会引用最近一次基线。

项目列表保存在本地 SQLite，页面会把当前项目 ID 保存在浏览器本地存储；重启服务或刷新页面后可继续查看原项目。恢复或切换项目时会同步回填该项目的硬件档案，无硬件档案或取消选择时会清空表单，避免把上一项目的配置误存到当前项目。报告请求和长任务轮询都绑定当前项目；切换项目、请求失败或返回 404 时会丢弃旧 UI 状态并释放运行槽位。

项目、运行、产物、来源和报告记录都在 API 边界携带 `schema_version: 1`；运行结果和产物 metadata 也保留该版本，后续字段迁移可以按版本读取，不会把旧证据静默当成新格式。

运行记录还带 `evidence_scope`：`local_software`、`training_or_simulation`、`bench_evidence`、`real_hardware` 或 `unknown`。报告不会把本机预检、训练 smoke、台架输入和真实主控/舵机结果混成同一种“通过”。

报告和 `/api/projects/{id}/next` 会为下一项任务返回完整任务卡：预计用时、所需工具、可执行步骤、前置条件、操作范围、所需证据、通过条件、失败处理、结果产物、风险和是否只读；首页直接显示同一份内容。装配、标定和部署任务还会返回结构化 `evidence_reasons`，说明当前缺少记录、硬件绑定或人工核验。任务卡复用现有任务图，不新增第二套流程状态。

登记本地来源时会只读扫描 Git commit、分支和已跟踪工作树状态；commit 留空时使用实测值，手工填写时同时记录它是否与实测值一致。URL 或不存在的路径不会触发网络访问。

项目资料搜索接口 `GET /api/projects/{id}/search?q=...` 只读取项目目录内的文本文件，跳过 Git/虚拟环境/构建目录和大文件，返回相对路径、行号和脱敏摘要；它不会联网，也不会执行搜索结果中的命令。结构化证据搜索接口 `GET /api/projects/{id}/evidence-search?q=...` 可选用 `type` 和 `status` 筛选，只返回运行、产物、来源、实验和问题的类型、ID、状态及命中字段，不返回完整日志；`GET /api/projects/{id}/evidence/{evidence_id}` 可读取同项目的脱敏详情，首页搜索后可直接载入首个结果。

硬件档案采用追加版本，报告中的 `hardware` 是最新版本，`hardware_history` 保留全部确认/待确认变化。

硬件档案还会独立计算完整性：舵机数量、主控型号、IMU、供电电压、打印件版本、运行时版本和训练仓库版本缺一项都会列入 `missing_fields`。这不会把已确认的舵机型号自动改回未确认，但会在 JSON/Markdown 报告和首页提示资料缺口。

硬件档案采用物理契约判定证据是否仍适用：舵机、主控、IMU、供电、打印件等物理字段变化会让主控诊断、舵机体检、装配、标定、辨识、训练 smoke 和报告任务退回待验证；只更新运行时或训练仓版本时，保留物理装配/标定/舵机证据，但仍要求重新执行受影响的软件检查和部署预检。相同档案重复保存不会制造新的失效。

任务图还包含“装配与电气验收”“标定记录确认”“部署前兼容性预检”“部署策略与健康检查”和“逐级实机验收”。兼容性运行依赖硬件确认、开发机预检和 smoke；真正生成部署计划时，还必须有当前硬件的装配检查全通过，以及带操作者明确核验的标定记录。部署执行会独立记录任务状态，只有上传、远端哈希、加载和健康检查都通过才算成功；它不代表站立或行走验收通过。硬件变更会同时使这些证据失效。

逐级实机验收接口 `POST /api/projects/{id}/acceptances` 只保存人工证据，不发送控制命令。阶段固定为 `lifted_enable`、`supported_stand`、`free_stand`、`supported_step`、`free_walk`：必须按顺序进行，每一级都要求操作者、检查结论和非空证据；失败会停止升级，通过复测可继续。只有五级均通过才完成任务，新的部署会自动使旧验收失效。JSON/Markdown 报告保留对应部署运行、硬件档案、规则版本和逐项证据，首页显示下一验收阶段。
依赖任务重新失败或不再成功时，已经标记为成功的下游普通任务会自动退回 `blocked`；失败和中断运行仍保留原始状态与证据，待前置条件恢复后再重新执行。

舵机探针还会绑定启动时的硬件档案版本；如果探针运行期间档案被替换，旧探针结果只保留在运行记录中，不会恢复舵机任务的通过状态。

确认 HL-2915 路线后，可调用 `POST /api/projects/{id}/bench/probe-plan` 生成固定的只读探针计划。默认兼容旧调用仍使用 `hl2915_mixed_probe`；只有已经接入 ID=200 IMU 时才把 `include_imu` 设为 `true`。新手只有两只 HL-2915、还没有 IMU 时，应保持 `include_imu=false`，工作台会调用不依赖 IMU 的 `hl2915_probe`，先完成 S0–S3。计划只接受明确串口、1–199 舵机 ID 和最长 300 秒观察时间；不会启动命令，也不会允许舵机 ID 占用 IMU 的保留 ID=200。

`GET /api/serial-ports` 只读取操作系统可见的串口名称（Windows 注册表或 Linux/macOS 设备节点），不打开设备、不读取寄存器，也不根据 USB 转接板名称推断舵机型号；界面仍要求操作者把端口与实际接线确认后再执行探针。

页面不会预填 `COM3` 或其他猜测端口；先点击“列出本机端口（只读）”，再把你实际确认的端口填入探针和 BAM 计划。

需要实际读取时，`POST /api/projects/{id}/bench/probe` 必须显式提交 `confirm: true`。服务仍只执行上述固定命令数组（`shell=false`），保存 stdout、stderr、退出码、完整时长和 `watch complete` 摘要；超时、进程异常、缺少摘要、通信错误或 IMU 未就绪都不会判定为通过。混合探针还要求至少 25 个样本、完整舵机故障计数和 `max_stale_run < 25`；旧版摘要不能冒充当前证据。

连续测试和只读探针的失败结果还会保存 `current_facts`、`possible_causes`、`missing_evidence` 和 `next_checks`；这些是基于实际判定原因的排查提示，不会自动修改串口参数或触发运动。连续测试原始输入中的 `cancelled` 也必须是布尔值，类型不可信时保持证据不足。

台架探针在 SQLite 事务和本地互斥锁下独占运行中的 HL-2915 总线；第二个探针请求会返回冲突，服务重启后遗留的运行会先标记为 `interrupted`。

探针请求会立即返回运行 ID；通过 `GET /api/runs/{run_id}` 查询结果，或 `POST /api/runs/{run_id}/cancel` 中止当前运行。取消后的最终状态是 `interrupted`，不会被当作通过；POSIX/WSL 下取消和超时会终止独立会话的整个进程组，Windows 使用父进程回退。页面为台架（含 BAM）和训练分别维护运行槽位，刷新报告时会按持久化运行记录恢复仍在运行的任务，避免取消按钮指向另一类运行。

失败或中断的只读探针和 CPU smoke 可从运行记录显式确认后重试；重试会重新执行当前硬件/环境前置检查，并在 JSON、首页和 Markdown 运行记录中保存 `retry_of`；BAM、部署等高风险运行仍需手动生成新计划。

报告页可在人工确认后把最近失败或中断运行直接生成问题草稿，保留运行诊断中的事实、原因、下一项检查和证据引用。

主控诊断先调用 `POST /api/projects/{id}/controller/diagnostic-plan` 查看固定 SSH 参数，再由 `POST /api/projects/{id}/controller/diagnostic` 配合 `confirm: true` 执行 `robotctl health --json`。它不接受远程 shell 文本，不启用密码交互，不自动接受未知主机；结果会区分主控不可达、`robotd` 不可用、机器人健康失败、版本/软件告警和证据不足。

每次诊断还会生成 `current_facts`、`possible_causes`、`missing_evidence` 和 `next_checks`，这些内容会进入 JSON/Markdown 报告和首页摘要；缺少或结构损坏的软件告警/服务列表时保持证据不足，不会把缺字段当作空列表。它们是带证据的排查提示，不是自动修复或运动指令。

策略包检查接口 `POST /api/projects/{id}/policy/inspect` 读取项目根目录内的 ONNX 与 `manifest.json`，规范化 `obs_len`、`action_len`、舵机型号、控制频率、action scale、关节单位/零位、IMU 坐标系和训练来源，并登记两个文件的 SHA-256。显式的 `0`、`false` 或空结构不会被静默回退到嵌套默认值；多策略 manifest 必须指定 `policy_name`；检查不会加载 ONNX、训练或部署。

实验记录支持用 `POST /api/projects/{id}/experiments` 建立、用 `PATCH /api/experiments/{id}` 更新、用 `POST /api/projects/{id}/experiments/{experiment_id}/link-run/{run_id}` 关联同项目的已完成运行作为证据，并用 `POST /api/projects/{id}/experiments/compare` 按两个同项目实验 ID 比较变量、基线、预期、结果、决策、状态和证据引用；运行未结束时不会被当作证据，重复关联不会重复写入。项目报告会把证据引用解析为运行类型、终态和证据范围。首页也可直接录入实验结果、结论和证据引用，关联运行后会把运行结果载入结果框供人工复核，不会自动冒充实验结论。建立时自动快照当前硬件档案、最近一次开发机预检和可选用户条件，原记录保持不变，跨项目或同一实验比较会被拒绝。

标定记录接口 `POST /api/projects/{id}/calibrations` 只接受当前已确认硬件，并结构化校验舵机名称、ID（0–253 且唯一）、方向、零位、角度限位和可选 IMU `frame/rpy_deg`；只有 `verified: true` 且提供 `operator` 的记录，才会把标定任务标记为成功并满足部署计划前置条件。它只保存可追溯数据，不宣称已经完成物理标定，也不写舵机寄存器。硬件档案变化后，历史记录仍保留但会标记为不适用于当前硬件；可通过 `GET /api/projects/{id}/calibrations` 查看。

装配记录接口 `POST /api/projects/{id}/assemblies` 保存资料引用、物料状态/数量/规格/来源/替代件/价格、装配/上电检查和照片或测量证据；`passed` 检查必须带证据，缺料会把完成度标为阻塞，并返回物料数量与状态摘要，记录只表示人工清单状态，不自动判断尺寸、接线或安全。硬件档案变化后，历史装配记录会标记为旧硬件；通过 `GET /api/projects/{id}/assemblies` 查看。

脱敏支持包接口 `POST /api/projects/{id}/support-bundle` 必须显式提交 `confirm: true`，且只能在项目根目录内新建 `.zip`、不能覆盖已有文件。支持包仅包含脱敏后的 `report.json`、`report.md` 和 manifest；递归隐藏密码、PSK、PIN、SSID、token、私钥、Bearer/GitHub token 及用户主目录，并登记为带 SHA-256 的 `support_bundle` 产物。自动脱敏不是分享授权，发送前仍需人工复核。

执行器辨识接口 `POST /api/projects/{id}/identifications` 记录现有 `hl2915_bench_summary.py` 的通过摘要、BAM 拟合文件、拟合次数、适用条件和独立验证 MAE。工作台会检查型号是否匹配当前硬件、摘要是否无 faults/errors、拟合文件是否存在，以及是否使用独立验证，并给出 `failed`、`inconsistent`、`incomplete` 或 `ready_for_simulation`；最后一种只表示可以进入仿真验证，不表示已经完成整机辨识或真机通过。历史记录可通过 `GET /api/projects/{id}/identifications` 查看。

辨识采样计划接口 `POST /api/projects/{id}/bench/bam-plan` 只在已确认 HL-2915 路线和舵机只读体检成功后生成固定的 `hl2915_bam_record` 参数数组。它限制单舵机 ID、质量、摆臂长度、幅度、时长、采样率和项目内 JSON 输出路径，明确要求实体急停与 `--confirm-motion`；接口只生成计划。执行接口 `POST /api/projects/{id}/bench/bam` 还要求 `confirm` 与 `confirm_motion` 双重确认，后台保存运行、取消/超时状态，并且只有新生成且可解析的非空 BAM JSON 才通过；输出会登记为带 SHA-256 的 `bam_raw` 产物。

问题台账接口 `POST /api/projects/{id}/issues` / `PATCH /api/issues/{id}` 保存症状、严重度、可能原因、下一项检查、证据引用和解决结论；首页也可直接更新状态、解决结论和证据，并可用 `POST /api/projects/{id}/issues/{issue_id}/link-run/{run_id}` 关联同项目的已完成验证运行。运行中不会被当作证据，重复关联不会重复写入；Markdown 报告会保留解决结论和证据引用。`POST /api/projects/{id}/issues/from-run/{run_id}` 可从已有失败运行带入诊断 guidance。带入结果仍需人工确认，不会自动修复或触发运动。

部署前兼容性接口 `POST /api/projects/{id}/deployment/preflight` 会读取当前已确认硬件、规范化策略 manifest，并与提交的运行时约定严格比较观测/动作维度、舵机型号、控制频率、action filter、action scale、关节单位/零位和 IMU 坐标系，以及出现时的 model API、硬件版本和关节顺序。若策略或运行时声明了关节顺序、零位或 IMU 帧，预检会优先使用当前硬件对应且已人工核验的标定记录补充实际契约；没有该证据时返回 `insufficient_evidence`。它只登记预检运行和策略产物，不部署。新增兼容性判定规则版本为 `compatibility-v2`。

部署计划接口 `POST /api/projects/{id}/deployment/plan` 只在最新预检通过、当前装配任务和已核验标定任务成功、标定记录 ID 与预检记录一致、硬件档案未变化且策略文件 SHA-256 未变化时生成计划。任何新的标定记录都会使旧部署预检失效；刷新任务状态时还会重新核对预检保存的策略/manifest 哈希和前置任务，文件被替换或删除、或前置检查失败时，部署预检会退回 `ready`/`blocked` 并显示需重验原因。`POST /api/projects/{id}/deployment/execute` 还要求显式 `confirm: true`，只执行固定 SSH/SCP 参数：读取旧 walk 路径、上传、核对远端 SHA-256、加载、健康检查，失败时恢复旧路径（没有可用旧路径则 reset）并清理临时文件。加载当前 walk 槽可能触发归位和重新驱动，执行前必须架空或可靠约束机器人并确保实体急停可用。

CPU smoke 训练接口 `POST /api/projects/{id}/training/smoke-plan` 会验证已确认硬件、成功预检、`bash`、`uv` 和独立训练 checkout，并生成仓库已有的固定 5 次迭代命令。计划与运行记录会保存训练 checkout 的 Git commit、分支、已跟踪工作树状态和固定配置；当前脚本未声明的执行器模型、随机种子和 checkpoint 明确记录为不可用，不会补默认值。运行结束还必须发现本次新生成的 ONNX 和 `check_onnx_contract.py` 合同 JSON；旧产物、缺失产物或合同形状/有限值证据不再被当作通过，合同文件会登记为 `onnx_contract` 产物，ONNX 保留外部路径与 SHA-256。原生 Windows 只生成计划，真实执行需把服务放在 Linux/macOS/WSL2。`POST /api/projects/{id}/training/smoke` 需要显式 `confirm: true`，后台运行后通过运行 ID查询或取消；结果会检查退出码以及日志中的 `NaN`、观测/动作维度错误。训练只写入指定 checkout，不操作硬件。

TensorBoard 摘要接口 `POST /api/projects/{id}/training/tensorboard-plan` / `training/tensorboard` 只接受训练 checkout 内的 run 目录，并把 `scalars.csv`、`summary.md` 和 `metrics.png` 写入项目根目录内的输出目录；执行前要求 smoke 任务已通过，成功后自动登记三个带 SHA-256 的产物。

服务重启时会把仍处于 `running` 的运行记录改为 `interrupted`，并写入 `service_restarted`；结果对象的 `status` 与运行行同步，若该运行对应的任务仍在运行，任务也会同步改为 `interrupted`，不会把中断任务误报为成功。

报告可通过 `/api/projects/{id}/report` 获取 JSON，或通过 `/api/projects/{id}/report.md` 获取 Markdown；`/api/projects/{id}/next` 返回按依赖计算的下一项任务，首页报告同时列出最近实验的 ID、状态和结论、问题台账状态/解决结论/证据，以及最近装配的完成度、物料数量和缺料状态。运行、产物或来源 ID 出现在实验/问题证据引用中时，报告会派生显示运行终态/证据范围、产物完整性/路径或来源位置/版本一致性，不复制原始大日志。硬件保存、预检、记录保存和长任务进入终态后，首页会自动刷新报告，避免继续显示旧的下一步。来源和版本通过 `POST /api/projects/{id}/sources` 登记，也可用 `GET /api/projects/{id}/sources` 单独读取，便于资料页刷新而不加载完整报告。产物通过 `POST /api/projects/{id}/artifacts` 登记，服务会限制在项目根目录内并计算 SHA-256；报告读取时重新核对文件，显示 `verified`、`changed`、`missing` 或 `unreadable`，不会把已被替换或删除的文件继续显示为可信证据。实验通过 `POST /api/projects/{id}/experiments` 建档，再用 `PATCH /api/experiments/{id}` 保存结果和决策。兼容性核验接口 `POST /api/projects/{id}/compatibility` 会要求硬件、策略和运行时同时提供动作维度、控制频率和 action filter 等证据，并在字段出现时严格比较 model API、硬件版本和关节顺序；空字符串、错误类型或缺字段返回 `insufficient_evidence`，不会误报通过。

本机全局 Python 若有 FastAPI/Pydantic 版本冲突，请使用上面的 `uv run` 隔离环境，不要修改仓库根目录的 Python 环境。
