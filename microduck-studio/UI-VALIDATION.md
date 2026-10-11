# Microduck Studio 界面优化验收

日期：2026-09-13。

本轮围绕既有个人本地工作台优化 UI，没有扩展设备驱动、运动能力或策略部署能力。修改集中在 `web/index.html`、新增的 `web/studio.css` / `web/studio.js`，以及 FastAPI 的静态资源挂载。模型图来自仓库现有渲染。

## 交付

- 总览：下一项任务、真实任务进度、阻塞原因、近期运行及证据范围。
- 导航：九个工作分区与模块子页；宽屏任务页采用步骤 / 操作 / 证据三栏，窄屏收拢。
- 表单：硬件部件选择、连续测试计数、问题描述；高级参数和原始结果按需展开。
- 反馈：操作期间禁用重复提交、网络错误提示、中文状态、规则版本、相关排查建议。
- 连续性：导航保留输入，报告刷新保护未保存内容；项目切换清理旧表单、记录与曲线。
- 运行入口：后台任务在任意页面提供中止按钮；手机隐藏硬件运动与部署启动。
- 资料：本地搜索快捷键、已有记录编号提示、Markdown 报告下载。

## 验证结果

- `uv run --extra test pytest -q`：208 passed。
- 外部 JavaScript 与页面内联 JavaScript 的 Node 语法检查通过；`git diff --check` 通过。
- `tests/ui-smoke.js`：6 组浏览器检查通过，包含阶段导航、表单隔离、输入保留、下一步入口、四档宽度及移动端操作边界。
- `tests/ui-workflow.js`：12 组实际交互检查通过，包含项目创建、硬件与部件持久化、未确认门禁、空证据与不足时长判定、问题保存、本地搜索、空遥测不补零、网络失败恢复、项目清理，以及全部模块子页在 375 / 768 / 1024 / 1440 px 下无页面横向溢出。无页面脚本错误。
- 另用模拟 API 验证运行恢复、手机总览中止与终态后清理入口；未创建训练进程。
- 工作流写入验证使用 8766 端口的独立临时数据库和 `/tmp/microduck-studio-ui-fixture`，未将模拟硬件或实验样本写入日常项目。

## 运行与边界

日常服务运行于 `http://127.0.0.1:8765`，应使用 `uv run python -m microduck_studio` 启动，以使子进程和只读预检继承项目虚拟环境的 PATH。直接调用虚拟环境 Python 而未激活 PATH 时，原有预检会将 PATH 中缺少 `python` 判为失败；本轮已校正服务启动方式并实际执行只读预检，结果通过，历史记录保留。

本轮未打开舵机串口、执行 SSH 硬件诊断、启动训练、产生运动或部署策略。软件与模拟 API 验证不能替代实机验收。


## 2026-09-13 · Color Studio 集成与可视化装配

- 本轮新增同源 3D 工作区、按项目保存的外观/耗材版本、旧版恢复、版本冲突保护，以及模型零件与装配检查的双向定位。
- 装配物料和证据、关节 ID/方向/零位/限位、IMU 姿态和条件改为表单。新关节与 IMU 的测量值留空；既有 JSON 可继续导入。草稿保存在当前标签页并按项目隔离。
- 修复 3D 页面隐藏时零尺寸导致的相机取景异常，以及关节输入失焦时整表重绘导致下一输入值丢失的问题。
- 修复 Color Studio 原锁文件中指向临时目录的错误包路径；保留 package.json 约束，`npm ci` 可独立完成。构建不读取工作区其他仓库。

验证：Studio `uv run pytest -q` 为 **222 passed**；Color Studio `npm test` 为 **16 passed**，`npm run build` 通过。新增 `tests/ui-visual.js` 的 **25 项**浏览器检查通过，无脚本异常；原 `tests/ui-workflow.js` 的 12 组回归通过。包括颜色/撤销、库存、版本与恢复、项目切换和刷新、冲突拒绝及草稿保留、3D 到检查项、无证据拒绝、硬件未确认标定门禁、实际输入往返、IMU、模型展开和 1440/1024/390 px 布局。合法失败的 400/409 为预期，不属于脚本异常。

所有写入测试都运行在 8766 的 `/tmp/microduck-studio-visual-validation.db`，样例证据明确注明为软件测试；日常 8765 项目仅用于只读展示。没有启动串口、运动、SSH、训练或部署。模型仍是 XL330 参考几何，未进行 HL-2915 实物适配验收。

本轮截图：`visual-desktop.png`、`visual-mobile.png`、`assembly-visual.png`，位于本次 Codex 可视化产物目录。首个视图为完整 WebGL 模型，非静态截图替代。

## 2026-09-13：安装教程、参考物理回放与下拉框

验证使用 `/tmp/studio-guide-validation.db` 与 8766 端口；日常项目未写入测试记录。

- Python：229 项通过，新增覆盖电压窗口、未知 SKU、候选状态不能升级为实机通过、版本冲突与项目隔离、模型部位覆盖、缺少环境的拒绝执行、跨项目轨迹隔离及中止优先于已生成轨迹。
- Color Studio：19 项通过；新增部位筛选、完整姿态恢复与无效矩阵拒绝；TypeScript / Vite 构建通过。
- 浏览器：桌面与 375px 窄屏下，下拉箭头与文字留白正常，窄屏为 16px 字号，页面无横向溢出。使用真实页面验证 HL-2915 / 3S / Radxa / IMX219 方案保存与待补证据；安装步骤加入清单保持待检查；历史轨迹能恢复，换色和时间轴可用，控制台无错误。
- 实际本地执行：原版 MuJoCo 重力参考过程、现有 CPU smoke 与 expE ONNX 回放均产生完整 5 秒 / 126 帧轨迹。实测中止请求的终态为 `interrupted`，`trajectory_available=false`。
- 限制：这些结果是软件和参考仿真证据。未操作串口、舵机或机器人；未新训练策略，未证明候选硬件已兼容。硬件方案到自定义训练执行器的自动参数注入尚未实现。

## 2026-09-14：方案训练、ONNX 与同环境回放

- 新增“仿真与训练 → 方案 → ONNX”。按保存版本选择方案，核对 MJCF 关节/传感器接口与 BAM M6 参数，将电源窗口、固件增益和延迟真正注入 CPU 环境。模型、网格、BAM、训练源码及未提交修改均有独立快照和校验值。
- 先检查输入再启动独立执行进程；与原训练入口共享执行锁。超过 5 轮需要同配置小规模实验。运行恢复显示真实轮数，全局中止入口支持新的实验类型；源码或输入变化后拒绝旧计划。
- runner 导出含归一化的 ONNX，并和训练策略在真实观测上的输出比较。导出策略在同一训练环境中回放 5 秒，保留随机化和自动重置。下载时校验文件完整性。
- 历史仿真可选择方案训练轨迹；暂停、切换页面和拖动时间轴不会停止任务状态跟踪。展示使用已核对的模型绑定，历史回放也会检查当前 GLB；不匹配时保留原始轨迹下载。

验证结果：

- Studio：**250 passed**。新增覆盖参数类型/范围、未知执行器拒绝、方案与输入快照、未提交源码保留、变更拒绝、跨项目隔离、训练锁、长训练前置条件、启动失败、单次计划、中止优先、重启中断、产物篡改和展示模型变更。
- Color Studio：**19 passed**，TypeScript / Vite 构建通过；新旧页面 JS 语法检查和 `git diff --check` 通过。
- 实际本地最终运行：`d9c5fce44386455a8c6760faeea24a9b`，4 环境 × 2 轮 × 24 步，XL330 M6 / 5 V / KP 200 / 延迟 3–6 步。训练、checkpoint、ONNX 与同环境回放均完成；ONNX 输出最大差 `1.1548399925231934e-07`，5 秒 / 126 帧，自动重置 5 次，躯干高度范围约 0.077–0.129 m。这不构成行走通过。
- `sources.zip` 保存 52 个源文件，实际核对其中未提交的 `microduck_velocity_env_cfg.py` 与当时工作树字节一致。ONNX、checkpoint、清单、轨迹和源码下载返回成功并匹配记录哈希。
- 浏览器实际操作：准备 → 启动 → 结果下载入口 → 历史结果 → 3D 回放；换色和 2.40 s 时间轴有效，无脚本异常。刷新后的 100 轮实验显示实际 100 轮，切至总览仍可中止；两次中止最终均为 `interrupted`、`artifacts_available=false`。HL-2915 候选方案显示缺少专用 BAM 并禁用启动。
- 375 px 窄屏无页面横向溢出；下拉控件 16 px 字号、38 px 右侧留白；视口测试后已恢复默认尺寸。

全部实验写入 `/tmp/studio-pipeline-validation.db` 与对应 `*-workbench/`，未写入日常“我的鸭子”的实验记录。日常 8765 服务已更新。当前适配范围是保持原版关节契约的 XL330 M6 方案；其他型号需要专用执行器、相应 MJCF 和实测辨识。主控/摄像头/打印件的质量与惯量以指定 MJCF 为准，下拉选型不自动生成结构。未操作串口、SSH、舵机或机器人，未部署策略。

## 2026-10-02：URT2 调试台（Web Serial 直连）

「舵机实验室 → URT2 调试台」新增第三个子页，把 duck.whatled.com 网页版调试台（解读 203 实测版）的功能完整移植到工作台：连接（型号/波特率/ID/PING/REBOOT/一键初始化）、150 ms 遥测（位置、电压、温度、电流、速度/负载、状态位、丢包）、位置控制（滑条、±600 步限幅、到位或 3 秒超时自动关扭矩）、增益与 EEPROM 保护参数（55 号锁位检查）、原始寄存器读写、总线扫描（ID 1–253）、多舵机总览表、改 ID 与可导出的操作日志。串口由浏览器 Web Serial 持有，Python 服务端无任何新增串口路径；这里的操作不写入 SQLite、不进入任务图与证据。

- 前端：新增 `web/servo-debug-studio.js`；`web/studio.js` 注册子页 tab；`web/studio.css` 新增调试台样式段；`web/index.html` 接入脚本并统一 `20261002-servodebug-1` 缓存版本。
- 危险动作（REBOOT、中位校准、原始写、改 ID）保留确认对话框；运动类按钮沿用 `dangerous-start`，375 px 窄屏隐藏，急停与遥测开关保留；不支持 Web Serial 时显示提示并禁用连接。

验证结果：

- Studio `uv run pytest -q`：**250 passed**（前端改动不触及服务端）。
- `node --check` 通过于 `servo-debug-studio.js` 与 `studio.js`；`git diff --check` 通过。
- 新增 59 项 Playwright 浏览器检查通过（临时库 + 8766 隔离服务）：子页切换、连接门禁按钮初始禁用、字段齐备、型号切换回填电压上限并写日志、滑条与数字双向同步、删除 `Navigator.prototype.serial` 后提示并禁用连接、375/768/1024/1440 px 无横向溢出、手机隐藏运动按钮且保留急停/遥测、切页后子页选中记忆、无页面脚本异常。
- 既有 `tests/ui-smoke.js`（6 组）与 `tests/ui-workflow.js`（12 组，8766 + 临时库 + `/tmp/microduck-studio-ui-fixture`）回归通过。
- 桌面与 375 px 截图核对：布局与工作台风格一致，窄屏单列且字号 16px。

本轮未打开串口、未连接舵机、无运动；协议代码为解读 203 实测页的忠实移植，实机行为仍以台架实操为准。

## 2026-10-03：前端上 Cloudflare Pages（API 留在本机）

工作台网页可部署到静态托管（Cloudflare Pages），API/SQLite/串口/训练留在本机。`web/app-config.js` 统一解析 API 地址（同源=原行为；公网来源默认 `http://127.0.0.1:8765`，可在「云端与本机」卡片按浏览器覆盖）；`studio.js`、三个子模块与 index.html 内联脚本共 110 处请求全部经由该解析器。服务端新增 `GET /api/version` 与可选 CORS：`MICRODUCK_STUDIO_ALLOWED_ORIGINS` 精确 Origin 白名单，默认空 = 与原行为一致，开启时回答含 Private Network Access 的预检。

- 新增 `scripts/build-pages-dist.py` 与 `wrangler.toml`；`pages-dist/`（23 个文件 10.6 MiB，含 Color Studio 3D 产物）已构建验证并 gitignore。
- 新增「项目与设置 → 云端与本机」卡片：服务地址保存/清除、解析提示、`/api/version` 连接与版本显示（版本偏差仅提示）、不可达地址的明确失败提示。

验证结果：

- Studio `uv run pytest -q`：**256 passed**（新增 `tests/test_cors.py` 6 项：默认无 CORS、白名单解析、允许来源的预检/实际响应头、Private Network 预检、相似后缀与未登记来源拒绝；`httpx` 加入 test extras）。
- 跨源 E2E（Playwright，8766 页面 → 8767 API，白名单指向页面来源）：跨源 GET 读列表、跨源预检 POST 创建项目、版本检测文案、不可达地址提示与恢复全部通过，无非预期脚本异常。
- 既有回归：`tests/ui-smoke.js` 6 组、`tests/ui-workflow.js` 12 组、URT2 调试台 59 项检查全部通过（同源路径行为不变）。
- `node --check` 通过于全部改动 JS；`git diff --check` 通过；`/api/version` 与页面卡片截图核对正常。

同日补充：已实际完成部署并线上验证。

- `wrangler pages project create microduck-studio` + `wrangler pages deploy`：23 个文件（约 8.8 秒上传），生产地址 **https://microduck-studio.pages.dev**。本机服务以 `MICRODUCK_STUDIO_ALLOWED_ORIGINS=https://microduck-studio.pages.dev` 重启，`/api/version` 确认白名单生效。
- 线上全链路（Playwright Chromium 从公网 URL 打开）：公网页面自动把 API 指向 `http://127.0.0.1:8765`；跨源 GET 读到项目列表与服务版本；跨源预检 POST 在公网→127.0.0.1 的完整 Private Network Access 链路下成功创建项目「云端部署验证 01:13:11」（写入日常库，属验证记录）；「云端与本机」卡片显示已连接；URT2 调试台在 Pages 来源下 Web Serial 可用；3D 视图 iframe 自 Pages 加载；无脚本异常与网络错误，顶栏连接指示为「本地服务已连接」。

## 2026-10-10：IMU 姿态台架（Web Serial 直连 ID 200）

「舵机实验室 → IMU 姿态」新增第四个子页（`web/imu-studio.js`）：浏览器经 Web Serial 直读舵机总线上 imu_to_dxl 节点（ID 200）的 FT6 契约块（寄存器 56–70，15 字节 = 陀螺 i16 ×3 ±500 dps + 四元数 binary16 x/y/z 主机重建 w + 采样计数 + 状态位 + 保留），与 15 颗 HD-1910 同一条 1 Mbps 半双工总线，服务端零改动、不进证据。显示：姿态仪（SVG 地平线）+ roll/pitch 大读数 + 相对偏航、陀螺三轴、四元数、计数与状态位解读（未就绪/过期>30ms/错误/节奏/保留位告警）、节点身份（固件 + 型号 'IM'）、实际速率与丢包。健康判据与节点侧一致：全零四元数或未就绪位保持上一份有效姿态；连续 3 次相同计数判疑似冻结。附姿态角与陀螺两条 SVG 折线、6000 行样本 CSV 导出、日志导出、静态零漂检查（10 s，±0.05 rad/s 门槛，deep-dive/68）。只读：不写寄存器、不改 ID；面板内提示与 URT2 调试台共用串口、直连前须停 robotd（单主站）。

- 前端：新增 `web/imu-studio.js`；`web/studio.js` bench tab 注册 `['imu','IMU 姿态']`；`web/studio.css` 新增 `#card-imu` 样式段；`web/index.html` 接入脚本、`window.ImuPanel.init()` 置于 `window.Studio.init()` 之前（tab 条从卡片构建），缓存版本 `20261010-imu-1`。
- 协议出处：kissqy 仓 `firmware/firmware/imu-source/README_FT6_SYNC15.md`；社区套件 `firmware/v1/docs/imu_to_dxl_protocol.md` §5.2/§6/§7.2（READ 指令、15 字节块布局、'IM' 型号寄存器、全零四元数=融合未收敛须保持上一有效值）。

验证结果：

- Studio `uv run pytest -q`：**299 passed**（含新增 `tests/test_imu_panel.py` 10 项：脚本与 init 顺序、tab 注册、CSS、FT6 块地址与长度、陀螺刻度与 w 重建、全零四元数保持上一姿态、过期/冻结判据、默认 ID 200、保留字节告警、零漂门槛、总线安全提示）。
- `node --check` 通过于 `imu-studio.js` 与 `studio.js`。
- Playwright 渲染检查（临时库 + 8770 隔离服务，Chromium headless）：bench 四个 tab 齐全、`#card-imu` 可见、14 项面板元素齐备、无页面脚本异常、375/768/1024/1440 px 无横向溢出；桌面全页截图核对：姿态仪天空/地平线/地面与红旗符号正确（修正过一处地平线画在 SVG y=0 而非圆心的几何错误）。
- 既有 `tests/ui-smoke.js` / `tests/ui-workflow.js` 未触及（bench 卡片为新增，不改既有元素）；`build-pages-dist.py` 整目录拷贝 `web/`，新 JS 自动随 Pages 发布。

本轮未打开串口、未连接实机；协议按已发布文档实现，实机行为待台架实测（LSM6DSV16X 模块或 imu_to_dxl 节点上电后直接可试）。
