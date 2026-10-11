# Microduck Studio

个人本地复刻工作台的持续实现。它管理项目、硬件档案、装配标定、台架测试、训练部署和证据记录；不直接写舵机、不替代 `robotd`，也不会自动选择 HL-1910 或 HL-2915。

## 工作台界面

首页按服务端任务图显示建议的下一步、前置阻塞、阶段进度和最近证据。左侧导航组织硬件、舵机、主控、装配标定、训练、部署、记录与资料；各模块用子页切换具体操作，右侧保留任务步骤、验收标准和中文结果摘要。原始结果可展开查阅。

- 硬件部件状态、连续测试计数和问题记录提供普通表单，原始 JSON 保留为高级入口。空计数和空遥测不会自动填零。
- 同项目切换页面保留输入，刷新报告不会覆盖未保存的硬件、偏好及训练目标；切换项目会清理前一项目的表单、记录编号、曲线和结果。
- 运行编号可以从现有记录中选择。最近运行可直接进入时间线，报告支持下载 Markdown。
- 后台台架和训练任务运行时，中止入口显示在所有页面的公共区域。手机保留查看与中止，隐藏硬件运动及部署启动按钮。
- `⌘ K` / `Ctrl K` 打开资料搜索，搜索框支持 Enter；子页支持方向键切换。界面适配 375、768、1024 和 1440 px，字体、图标和图片均由本机提供。

主工作台沿用本地静态网页与既有 API。3D 工作区复用本目录下独立的 `microduck-color-studio`，通过同源内嵌页面共享服务；其 TypeScript / Three.js 前端需要一次本机构建，日常运行只需 Python 服务。`web/studio.css` 管理样式，`web/studio.js` 管理展示与交互，任务判定继续由 Python 服务执行。模型图复制自 `microduck-replica/rl-series/assets/duck-render-03-四分之三.png`，只作仿真模型参考，不代表当前实物状态。

舵机编号对照集成自独立的 `microduck-servo-guide` 静态站点（HD-1910 版装配模型的 15 颗舵机 ID 标注）。服务启动时在其 `site/` 目录（本目录下，或与本目录同级的检出）找到 `index.html` 和 `model/model.json` 后，将站点挂载到 `/servo-guide/`，并通过 `GET /api/servo-guide` 返回可用性与结构化编号对照；找不到时该功能不可用，其他功能不受影响。“装配与标定 → 舵机编号 3D 对照”内嵌查看器并提供编号速查表，“舵机实验室”的通信验证卡附编号速查。边界与既有事实一致：这是纯查看工具，不打开串口、不读取或写入实机 ID；标注 ID 是项目关节编号的位置对照，不代表舵机出厂或实机已写入的 ID，装配姿态不是零位；模型与衍生网格遵循 CC BY-NC-SA 4.0（署名见站点 `credits.html`），不能当作 MIT 软件再分发。3D 页首次载入约 20 MB 网格，页面内需手动点击后才加载。

浏览器回归用例保存在 `tests/ui-smoke.js` 与 `tests/ui-workflow.js`，均为接收 Playwright `page` 的异步函数。前者在 8765 端口只读检查导航与布局；后者要求独立的 8766 服务，数据库必须通过 `MICRODUCK_STUDIO_DB` 指向临时文件，且 `/tmp/microduck-studio-ui-fixture/guide.md` 存在并含 `HL-2915`。后者会在临时库创建项目、保存记录、检查异常与各分区布局，不打开串口或执行训练部署。

## 3D 外观与可视化装配

左侧“3D 外观与装配”直接使用 Color Studio 的真实 GLB：逐件配色、材质和层纹、灯光、展开与隔离、标准视角、耗材录入及推荐、JSON 导入导出、PNG 导出、撤销与重做。点击模型零件后，可以将它加入当前项目的装配检查，并从清单返回 3D 定位。

- “保存到项目”把完整配色、耗材和模型来源保存到 SQLite `visual_configs`。每次保存追加版本；服务端校验全部零件、材质、颜色和模型编号，通过 `expected_revision` 拒绝旧窗口覆盖新版本。旧版载入为草稿，保存后形成新版本。
- 外观、装配和标定草稿按项目隔离，暂存在当前浏览器标签页的 `sessionStorage`；刷新和项目切换可恢复，关闭标签页前应保存到项目。独立 Color Studio 原有的浏览器全局库存不会自动导入，可用 JSON 导入到选定项目。
- 装配清单提供名称、资料、物料状态/数量/规格/来源/单价、零件关联、检查结果和证据的可视化编辑。记录保留稳定零件编号及模型清单 SHA-256；通过仍要求证据并由服务端判定。
- 标定提供关节 ID、方向、零位、角度上下限和范围示意，以及 IMU 坐标系、RPY、测量条件与验证人表单。新记录不预填测量值；这些操作只保存记录，不写入设备。高级 JSON 入口仍可导入已有数据。
- API：`GET /api/visual/model`；`GET/POST /api/projects/{id}/visual-configs`。版本记录不会解锁硬件任务。

模型来自 Pollen Robotics 原版 XL330 步行装配，70 个模型实例包含 36 个打印件实例；它不是实际采购 BOM，也没有验证 HL-2915 改件的尺寸。模型遵循 CC BY-NC-SA 4.0，原作者、来源和许可链接保留在 3D 页面。改动的配色不能作为硬件适配或装配验收证据。

## 集成开发工作台

当前版本把辅助开发收敛到同一个项目和运行记录中：

- 分阶段硬件：可为主控、单舵机台架、关节组、IMU、摄像头和整机记录 `planned`、`owned`、`installed`、`detected`、`verified` 或 `failed`，只解锁现有硬件能够完成的调试能力。
- 整机称重与 ID 对照：以官方 MJCF（`robot_walk.xml`）各 body 的显式 `inertial mass` 为分区域模板（一个 body 一个称重区域），支持整机对账、分区域实测（整称/倒推/镜像）、秤与操作者留痕；缺失区域保持证据不足，不用零值补齐。所有区域实测后可在显式确认下生成质量修正 MJCF 副本（惯量按质量比例缩放，不覆盖官方模板、不覆盖已有文件，模板 SHA-256 变化时拒绝生成并登记为产物）。同一卡片登记"舵机 ID ↔ 关节"映射——这是操作者对已写入总线的编号方案的记录，供 robotd 配置、标定与 BAM 使用，链路由只读探针另行验证；台架样机与整机存在相同 ID 时不得同时上总线。
- 受控训练：除固定 CPU smoke 外，可使用服务端内置 `walk` 配方生成和启动本机 Linux/macOS 或 WSL2 训练；参数经过范围校验，不接受任意 Shell。
- 显式续训：必须同时选择父训练运行和该运行已登记、哈希一致的 `.pt` checkpoint；硬件、观测动作或控制频率契约不一致时不会启动。
- 可视化调试：训练期间增量保存已脱敏、分段限长的标准输出/错误日志，并从 RSL-RL/MJLab 输出提取临时指标曲线；训练结束后的正式指标仍以 TensorBoard 产物为准。也可比较两个已结束运行的生效配置和数值指标。
- 项目配置：保存默认执行位置、可见指标和告警阈值；实际生效参数仍写入每次运行证据。
- 多端布局：同一网页在 PC、平板和手机上响应式排列。手机窄屏隐藏硬件运动和部署启动按钮，取消和只读查看仍保留；服务端确认仍是安全边界。

远程 GPU 目标可以登记并生成明确的“尚不可执行”结果；在远端 checkpoint 哈希和断线状态对账完成前，工作台不会把 SSH 长训练伪装成已支持。服务仍默认监听本机地址，不应直接暴露到公网。

### Microduck-kissqy 训练服务适配

“仿真与训练 → Microduck-kissqy”通过本机 Studio 服务连接独立运行的 kissqy 训练控制台。默认地址为 `http://127.0.0.1:8092`，可在启动 Studio 服务前设置 `MICRODUCK_KISSQY_URL` 更改 loopback 端口；出于本机服务边界，适配器拒绝公网地址、路径和内嵌凭据。上游一次性训练凭据只由 Python 服务读取，不下发到浏览器。

先在另一个终端启动上游服务：Linux/macOS 执行 `cd Microduck-kissqy/microduck-hd1910/training-console && bash start-training.command`；Windows 执行该目录下的 `start-training.cmd`。训练控制台显示已启动后再打开 Studio 的训练页；只连接服务不会排入任务或启动训练。

- 页面读取训练台版本、环境、已启用任务、队列、运行进度与最近指标；UI 展示版本，不因版本号不同自动判定不兼容。服务端也会检查实际接口是否存在。
- Studio 可添加一份带请求编号的训练配置快照；它只进入上游持久化队列，不会自动启动。开始和停止需要二次确认。超时后不会自动重发添加请求，刷新会先按上游请求编号对账，避免重复排队。
- 训练队列和外部运行会绑定当前 Studio 项目。服务端阻止当前项目操作启动、暂停或停止未关联到该项目的活动任务。完成运行可在同一页面读取日志、下载训练台导出的策略 ZIP；下载仅对已经关联的运行开放。
- 上游 `Microduck-kissqy` 面向其自身 HD1910 仿真路线。它的训练、标定、质量假设不会覆盖 Studio 的硬件档案，也不能证明其他舵机兼容或策略可部署；新型号仍须独立执行器模型、辨识、策略契约核验和实机验收。

适配器是针对本机 HTTP API 独立编写的代码，不复制上游训练台 UI、调度实现或资源。上游内容有分立的许可范围，尤其训练控制台许可和第三方训练引擎并不相同；集成后的再分发/商业使用须遵守 [Microduck-kissqy 的 LICENSE 与 NOTICE](../Microduck-kissqy/microduck-hd1910/training-console/NOTICE.md)。

## 运行

```powershell
cd microduck-studio
cd microduck-color-studio
npm ci
npm run build
cd ..
uv sync --extra test
uv run pytest -q
uv run python -m microduck_studio
```

打开 <http://127.0.0.1:8765>，3D 工作区为 <http://127.0.0.1:8765/#visual>。修改 Color Studio 源码后重新构建；首次构建后需重启 Python 服务以挂载静态目录。舵机编号对照无需构建：把 `microduck-servo-guide` 克隆或复制到 `microduck-studio/` 目录内（或与其同级），重启服务后挂载到 <http://127.0.0.1:8765/servo-guide/>。数据库默认写入 `microduck-studio/studio.db`，可用 `MICRODUCK_STUDIO_DB` 指定位置。页面默认把项目根设为启动目录的上一级（`..`），对应 Microduck 仓库；若资料在其他目录，请先修改路径。

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

### 可视化安装与硬件方案（2026-09-13）

打开 `#guide`：

- **安装教程**：8 个步骤对应原版装配的 15 个部位、70 个实例。支持按部位筛选、爆炸展开、显示内部硬件和零件定位；加入装配清单后仍为待检查，必须另存实测证据。
- **硬件与接线**：选择舵机、电源、主控和摄像头；查看尺寸、质量、协议、规格来源及电压窗口检查。未知规格保持不可用，电源和信号图是逻辑连接关系，不能替代具体连接器针脚表。
- **方案与候选库**：方案按项目保存版本、检查并导出 JSON；可登记新的完整舵机 SKU。候选规格不能自行宣称台架通过，不能借用另一型号的 BAM。CAD / MJCF、BAM 路径可由训练中心的“方案 → ONNX”页检查并生成输入快照。当前已接入保持原版关节拓扑的 XL330 M6 方案；HL-2915 等缺少专用适配的型号仍会阻止启动，不会借用其他型号参数。
- **参考物理仿真**：使用项目内 `microduck-replica/upstream/microduck_rl/.venv/bin/python` 和原版 `scene_walk.xml` 运行独立 MuJoCo 进程。可执行 5 秒未通电模型重力 / 接触演示，或选择本地 `logs/rsl_rl/velocity/*/*.onnx` 回放。ONNX 回放使用原版 XL330 M6 BAM、5 V、KP=200、3–6 控制步延迟、50 Hz 控制、61/14 维接口；参考环境将地面碰撞掩码扩展到原版机身碰撞组 2，配置与轨迹记录该差异。该环境不等同于策略训练域，也不是当前硬件或行走验收。
- **可恢复回放**：轨迹按 25 fps 保存，包含每个部位的变换矩阵、时间、躯干高度、源模型哈希、执行日志及配置；支持历史回放、暂停、拖动时间轴和换色。颜色只作用于显示。任务中止、超时、进程退出、读取错误不会生成可用的成功回放。

运行数据保存在数据库旁的 `<数据库文件名去扩展名>-workbench/`，属于本地实验产物。不要将目录加入版本控制。新页面沿用原有项目、任务及装配记录，未自动确认实际硬件，也未写入设备。

下拉框保留浏览器原生选项菜单和键盘交互；统一控件高度、文字留白、箭头、焦点及禁用状态，窄屏字号至少 16px。关联多个模型实例的装配检查显示其数量，避免单选框只显示最后一个关联零件。


### 方案训练与 ONNX（2026-09-14）

在“仿真与训练 → 方案 → ONNX”中：

1. 选择已经保存的硬件方案版本；也可新增“原版 XL330 · 5 V 参考训练方案”。参考方案不会确认或修改实际硬件档案。
2. 检查并准备：验证完整供电窗口、BAM 型号和参数、MJCF 关节顺序、传感器接口及 50 Hz 约定；将 MJCF 包含文件展开，连同实际网格/纹理保存为可独立编译的 ZIP，复制 BAM 并记录校验值。仅填写路径不足以通过检查。
3. 先进行默认 4 环境、2 轮、每轮 24 步的本地 CPU 实验。界面展示实际生效电压、固件增益、延迟与随机种子。当前入口最多 32 环境、1000 轮，超时 1 小时；超过 5 轮时必须有相同方案、输入模型、BAM、代码及执行器设置的有效小规模实验。
4. 执行进程完成训练后，使用上游 runner 导出含观测归一化的 ONNX，比较实际观测下 ONNX 与训练策略的输出，再将导出 ONNX 输入同一个训练环境回放 5 秒。回放保留训练随机化和自动重置，显示重置次数与躯干高度范围。
5. 下载 ONNX、checkpoint、实验清单与轨迹；原版展示几何匹配时可直接打开带项目配色的 3D 回放。新结构与原版几何不符时只提供真实轨迹数据，不强行套用原版外观。

训练和既有训练入口共用执行锁。日志与事件持续保存，页面刷新可以恢复跟踪，任意页面可中止；中断、异常退出、流读取失败或缺少产物均不能通过。旧计划只能执行一次，输入或代码变更后须重新准备。完成后的下载会重新核对产物 SHA-256。

供电窗口、BAM 文件、固件增益和延迟现在实际进入环境配置。此入口将电压压降随机化固定为 0，其他上游训练随机化仍保留，完整配置写在运行目录 `params/env.yaml`、`params/agent.yaml`。准备输入在 `plan-<id>/`，执行产物在 `<run-id>/`，均位于数据库旁的 `*-workbench/`。训练源文件（含未提交修改）、执行脚本、锁文件和任务配置按实际内容保存到 `sources.zip`，可随实验下载。清单还包含 Git commit/工作树摘要、训练源文件哈希、依赖版本、关节/观测/动作约定及 ONNX 输出误差。

这是候选方案的软件实验入口：`hardware_verified=false`、`deployment_ready=false`。运行完成不代表训练收敛、舵机通过台架或当前机器人适配成功。当前工作台仅核验 XL330 M6 的步行任务接口；新舵机还需要专用执行器实现、对应结构与实测辨识。既有“模型训练与续训”页仍按原流程执行，不会隐式采用此处选中的方案。

接口：`GET recipe-training/defaults`、`POST recipe-training/prepare`（`revision` / `parameters`）、`POST recipe-training/start`（`plan_id` / `confirm:true`），以及 `GET recipe-training/{run_id}/{name}`。均位于 `/api/projects/{project_id}/` 下；运行查询、事件和中止复用原有 `/api/runs/` 接口。

### 舵机调试台（URT2 直连 · 2026-10-02）

「舵机实验室 → URT2 调试台」把 duck.whatled.com 的网页版调试台（`duck-whatled/public/tools/servo-debug-web.html`，解读 203 台架实测版）完整搬进工作台，前端逻辑在 `web/servo-debug-studio.js`。它运行在浏览器里，通过 Web Serial（Chrome/Edge，`http://127.0.0.1:8765` 属安全上下文）直连 URT2 调试板；**串口由浏览器持有，Python 服务不会打开它**，与只读探针、BAM 的服务端串口互斥不冲突。功能与网页版一致：

- 连接：型号（HL-2915 / HL-1910 / 通用磁编码）、波特率、舵机 ID、PING、REBOOT 清锁、一键温和初始化；连接后自动读固件版本、电压窗和扭矩状态，并开始 150 ms 遥测。
- 遥测：位置/角度、电压（低于型号工作区告警）、温度、电流（6.5 系数口径待验证）、速度/负载、状态位（过压/欠压、磁编码、过热、过流、过载）与丢包计数；急停随时可用（手机端也保留）。
- 位置控制：目标位置 + 滑条、±600 步安全限幅（可解除）、速度/加速度，到位（±6 步）或 3 秒超时后自动关扭矩；扭矩开关与 40=128 中位校准。
- 增益与保护：P/D/I（21/22/23，RAM）写入与读回；EEPROM 行程、电压上限、温度上限、最大扭矩写入前自动检查 55 号锁位，掉电保存。
- 高级：原始寄存器读/写（写需确认）。
- 总线：PING 扫描 ID 1–253、多舵机实时总览表（选择/回中）、全部回中与全部扭矩开关、EEPROM 改 ID（一次只接一只）。
- 日志：带时间戳的操作日志，可导出 `.log` 文件，作为后续实验/问题记录的人工证据附件。

边界：调试台是台架实操工具，不产生运行记录、不写入 SQLite、不参与任务图；危险动作（REBOOT、校准、原始写、改 ID）保留确认对话框，运动类按钮沿用 `dangerous-start` 在手机窄屏隐藏。「不直接写舵机」指服务端——工作台后端仍未新增任何串口写路径。

### IMU 姿态台架（Web Serial 直连 ID 200 · 2026-10-10）

「舵机实验室 → IMU 姿态」新增第四个子页（`web/imu-studio.js`），直读舵机总线上的 imu_to_dxl 节点（kissqy IMU_TO_DXL / 社区套件 v1，主控 LSM6DSV16X）：节点把姿态伪装成总线 ID 200，与 15 颗 HD-1910 共用同一条 1 Mbps 半双工总线，浏览器经 Web Serial 用普通 READ 指令读它的 FT6 契约块（寄存器 56–70，15 字节 = 陀螺 XYZ i16 小端 ±500 dps + 四元数 XYZ binary16（主机侧重建 w）+ 采样计数 + 状态位 + 保留），协议出处为 kissqy 仓 `firmware/imu-source/README_FT6_SYNC15.md` 与社区套件 `firmware/v1/docs/imu_to_dxl_protocol.md` §6。串口仍由浏览器持有，服务端不碰、不进证据。功能：

- 连接：节点 ID（默认 200）、波特率（默认 1 Mbps）、目标采样率（50/20/10 Hz）；连接后先读身份寄存器（固件版本 + 型号 'IM'，0x4D49），随即自动开始遥测，显示实际速率与丢包/发送计数。
- 姿态显示：姿态仪（SVG 地平线，roll/pitch 驱动）+ 大号 roll/pitch 读数 + 相对偏航；陀螺三轴 °/s、四元数 x y z w、采样计数与状态位解读（FT6：bit0 未就绪、bit1 过期>30ms、bit2 错误、bit3 节奏提示、保留位非零告警）。
- 健康判据与节点侧一致：全零四元数或未就绪位 = 融合未收敛（上电约 1.5 s），保持上一份有效姿态而不画假零；连续 3 次相同计数判「疑似冻结」；过期位判「数据过期」。
- 曲线与导出：姿态角（roll/pitch）与陀螺三轴两条 SVG 折线（约 100 ms 刷新、240 点窗口）；样本环形缓冲（6000 行）导出 CSV，操作日志导出 `.log`；静态零漂检查（10 s）按 0.05 rad/s（±2.865 °/s）门槛逐轴判定（deep-dive/68 五步验收门槛之一），为后续 IMU+舵机联合标定预留预检。

边界：与 URT2 调试台共用物理串口、不能同时连接；总线同一时刻只允许一个主站，直连前必须停止机器人上的 robotd（面板内有提示）。只读面板——不写任何寄存器、不改 ID/波特率；状态位解读按 FT6 人格，接到 native 人格固件的节点时保留字节告警会提示口径差异。

### 前端上 Cloudflare Pages（操作仍在本机 · 2026-10-03）

工作台网页可以部署到 Cloudflare Pages 等静态托管，**API、SQLite 数据库、串口、SSH 与训练始终留在运行本机服务的那台电脑上**，不上云。`web/app-config.js` 解析 API 地址：本机同源访问时与原行为完全一致；从公网来源（如 `https://<项目>.pages.dev`）打开时自动指向 `http://127.0.0.1:8765`，也可在「项目与设置 → 云端与本机」按浏览器保存自定义地址。该卡片同时通过 `GET /api/version` 显示服务版本，页面与服务版本不同时仅提示、不拒绝。

部署：

1. `uv run python scripts/build-pages-dist.py` —— 生成 `pages-dist/`（页面 + `/assets` + Color Studio 3D 模型，约 10.6 MiB；目录已 gitignore）。
2. `npx wrangler login && npx wrangler pages deploy`（`wrangler.toml` 已指向 `pages-dist`）。
3. 本机服务带环境变量启动：`MICRODUCK_STUDIO_ALLOWED_ORIGINS=https://<项目>.pages.dev uv run python -m microduck_studio`。**默认为空 = 同源 only，与原先行为一致**；白名单按精确 Origin 匹配，`https://a.pages.dev` 不会放行其他 `*.pages.dev` 站点。
4. 打开 Pages 地址即可使用；「云端与本机」卡片应显示本机服务已连接。

当前部署：**<https://microduck-studio.pages.dev>**（2026-10-05，Account `Admin@sxyseo.com`）。日常启动本机服务请携带上面的 `MICRODUCK_STUDIO_ALLOWED_ORIGINS`；部署专属预览地址（`<哈希>.microduck-studio.pages.dev`）来源不同，不在白名单内，请使用生产地址。

边界与已知事实：跨源能力由 Starlette `CORSMiddleware` 提供，并回答 Chrome 对公网页面访问 `127.0.0.1` 的 Private Network Access 预检；Web Serial 调试台在任何 HTTPS 来源都可用（串口在操作者电脑上），仍限 Chrome/Edge。服务仍只监听 loopback——CORS 白名单只决定"哪些页面可以读响应"，不改变"只有这台机器能执行硬件操作"的事实。3D 视图与安装教程的 Color Studio 产物随 pages-dist 一起发布，其内部只读自身静态清单，不依赖本机 API。`microduck-color-studio` 源码变更后需重新 `npm run build` 并重跑第 1 步。
