# HL-2915 全链路证据闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `coding` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 HL-2915 → IMU/HAT/相机 → BAM/训练 → ONNX 部署之间仍可能“误报通过”的软件证据门槛补齐，同时保持没有实物时明确显示待验证。

**Architecture:** 继续复用现有 Rust 探针、Radxa 报告和训练脚本；只给证据文件增加不可伪造的文件身份、冻结 IMU 拒绝规则和有界 HAT 功能 smoke。`bringup_status.py` 是唯一总汇总入口，真实硬件仍由操作者逐门执行。

**Tech Stack:** Rust 1.89、Python 3 标准库、ALSA 工具、i2c-tools、现有 GStreamer/ONNX Runtime。

**Spec:** `docs/HL2915全链路落地手册.md`

## Global Constraints

- 不改动 `F:\microduck_rl` 的用户工作树；只读使用它已有的 ONNX 产物和 `uv` 环境。
- 不把编译、自检、synthetic 数据当作真机证据；硬件报告必须标注 `data_provenance=measured`。
- HAT 主动测试必须显式确认是官方 Robot HAT；未知 I²C 电路不扫描。
- HAT 测试不碰舵机扭矩；相机测试保持有界；模型部署前必须验证文件 SHA-256。
- 当前工作树已有大量用户修改，不创建提交，不重置或清理；每项用测试输出和 artifact 留证。

---

### Task 1: 给 ONNX 合同加入文件身份

**Files:**
- Modify: `tools/microduck_learning/check_onnx_contract.py`
- Modify: `tools/microduck_learning/bringup_status.py`
- Create: `tools/microduck_learning/test_check_onnx_contract.py`
- Modify: `tools/microduck_learning/test_bringup_status.py`

**Interfaces:**
- Consumes: 一个本地 `.onnx` 文件。
- Produces: 合同字段 `sha256: str` 和 `size_bytes: int`；S7 只有形状、有限推理、64 位小写 SHA-256 和正文件长度同时成立才通过。

- [x] **Step 1: 写文件身份失败测试**

```python
def test_file_identity_contains_size_and_sha256(tmp_path: Path) -> None:
    model = tmp_path / "policy.onnx"
    model.write_bytes(b"policy")
    assert file_identity(model) == {
        "sha256": hashlib.sha256(b"policy").hexdigest(),
        "size_bytes": 6,
    }
```

- [x] **Step 2: 运行红灯**

```powershell
python -m unittest tools.microduck_learning.test_check_onnx_contract -v
```

Expected: `ImportError`，因为 `file_identity` 尚不存在。

- [x] **Step 3: 用标准库实现文件身份**

```python
def file_identity(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "size_bytes": size}
```

让 `check()` 的返回值合并 `file_identity(path)`。

- [x] **Step 4: 写 S7 缺哈希拒绝测试并实现门槛**

测试分别覆盖：旧合同缺哈希时 `failed`；64 位十六进制哈希且 `size_bytes > 0` 时 `passed`。实现不得只检查字段存在。

- [x] **Step 5: 运行绿灯**

```powershell
python -m unittest tools.microduck_learning.test_check_onnx_contract tools.microduck_learning.test_bringup_status -v
```

### Task 2: 拒绝冻结或空的 IMU 混合日志

**Files:**
- Modify: `tools/microduck_learning/bringup_status.py`
- Modify: `tools/microduck_learning/test_bringup_status.py`

**Interfaces:**
- Consumes: `hl2915_mixed_probe` 的 `watch complete` 行。
- Produces: S5 仅在 `samples >= 25`、`errors=0`、`imu_ready=true`、所有舵机故障为 0、且 `0 <= max_stale_run <= stale_imu < samples`、`max_stale_run < 25` 时通过。

- [x] **Step 1: 写两个失败场景**

```python
def test_mixed_log_rejects_zero_samples_even_if_ready(self) -> None:
    # samples=0, imu_ready=true 必须 failed

def test_mixed_log_rejects_fully_frozen_imu(self) -> None:
    # samples=100, stale_imu=99 必须 failed
```

- [x] **Step 2: 运行红灯**

```powershell
python -m unittest tools.microduck_learning.test_bringup_status.BringupStatusTests.test_mixed_log_rejects_fully_frozen_imu -v
```

- [x] **Step 3: 扩展必需字段与判断**

解析 `samples`、`stale_imu` 和 `max_stale_run` 为整数；解析失败、样本不足、连续 25 帧冻结或旧日志缺字段都返回 `failed`，并在 `next` 中提示检查 IMU 固件刷新和总线数据。

- [x] **Step 4: 运行绿灯**

```powershell
python -m unittest tools.microduck_learning.test_bringup_status -v
```

### Task 3: 增加官方 Robot HAT 的有界功能 smoke

**Files:**
- Create: `tools/microduck_learning/hat_smoke.py`
- Create: `tools/microduck_learning/test_hat_smoke.py`
- Modify: `tools/microduck_learning/bringup_status.py`
- Modify: `tools/microduck_learning/test_bringup_status.py`

**Interfaces:**
- Consumes: 官方 HAT、`/dev/i2c-pihat` 或 `/dev/i2c-3`、ALSA 设备 `plughw:aic3104`。
- Produces: `hat-smoke.json`，含 `source=radxa`、`data_provenance=measured`、codec `0x18`、录音字节数、播放命令结果和人工听音确认。

- [x] **Step 1: 写纯 JSON 验证测试**

通过样例必须含 `codec.status=passed/address=0x18`、`capture.status=passed/bytes>44`、`playback.status=passed`、`audible_confirmed=true`。synthetic、空录音、错误地址或未确认听音都必须失败。

- [x] **Step 2: 运行红灯**

```powershell
python -m unittest tools.microduck_learning.test_hat_smoke -v
```

- [x] **Step 3: 实现最小运行器**

`--run` 必须同时要求 `--confirm-official-hat`；用参数数组执行 `i2cdetect -y -r 3`、两秒 `arecord` 和低音量临时 WAV 的 `aplay`。临时音频放 `TemporaryDirectory`，结束即删除；任何命令超时或非零都写入 JSON 并返回 1。

- [x] **Step 4: 把 HAT JSON 接入总状态**

增加 `--hat-smoke`；S6 必须同时满足板卡 inventory、HAT smoke 和 camera/media smoke。只有其中之一时保持 `pending`，失败证据不能被人工参数覆盖。

- [x] **Step 5: 运行绿灯和自检**

```powershell
python tools/microduck_learning/hat_smoke.py --self-test
python -m unittest tools.microduck_learning.test_hat_smoke tools.microduck_learning.test_bringup_status -v
```

### Task 4: 更新小白执行顺序和官方 HAT 边界

**Files:**
- Modify: `docs/HL2915全链路落地手册.md`
- Modify: `docs/新手学习文档.md`
- Modify: `tools/microduck_learning/README.md`
- Modify: `artifacts/README.md`

**Interfaces:**
- Consumes: Tasks 1–3 的真实命令参数。
- Produces: 可复制的 Radxa 执行顺序和每一步的“通过/失败/立即断电”判断。

- [x] **Step 1: 解释两颗 IMU**

明确 HAT 上 BMI088 是 I²C 器件且当前步态不用；真正控制闭环使用独立 `imu_to_dxl`、Dynamixel v2、ID 200，二者不能互相替代。

- [x] **Step 2: 增加 HAT smoke 命令**

```bash
python tools/microduck_learning/hat_smoke.py --run \
  --confirm-official-hat --confirm-audible \
  --json-out artifacts/hat-smoke.json
```

说明测试会录两秒临时音频并播放低音量提示音，不保留录音内容；听不到声音时不得使用 `--confirm-audible`。

- [x] **Step 3: 增加模型身份和总状态命令**

文档展示 `check_onnx_contract.py` 新字段，以及带 `--hat-smoke` 的 `bringup_status.py` 命令。

- [x] **Step 4: 更新软件回归数字和诚实边界**

只记录本轮真实测试输出；HAT、IMU、相机和舵机没有实物 JSON 时继续写“待验证”。

### Task 5: 使用现有训练产物做真实 ONNX 合同回归

**Files:**
- Write artifact only: `artifacts/onnx-contract-provenance-check.json`
- Write artifact only: `artifacts/bringup-status-current.json`

**Interfaces:**
- Consumes: `F:\microduck_rl\logs\rsl_rl\velocity\...lesson-01-repro.onnx`。
- Produces: 带 SHA-256/大小的真实 CPU 合同；刷新后的总状态报告。

- [x] **Step 1: 运行真实 ONNX 合同检查**

```powershell
Set-Location F:\microduck_rl
uv run python F:\microduck\tools\microduck_learning\check_onnx_contract.py <最新ONNX> --json-out F:\microduck\artifacts\onnx-contract-provenance-check.json
```

训练仓 Windows `.venv` 已损坏且不做破坏性重建；改用本机已安装的 ONNX Runtime 对同一真实文件完成 CPU 合同检查。

- [x] **Step 2: 刷新总状态**

```powershell
Set-Location F:\microduck
python tools/microduck_learning/bringup_status.py --onnx-contract artifacts/onnx-contract-provenance-check.json --json-out artifacts/bringup-status-current.json
```

- [x] **Step 3: 全量回归**

```powershell
cargo +1.89.0 fmt --all -- --check
cargo +1.89.0 test -p duck-control --all-targets --quiet
python -m unittest discover -s tools/microduck_learning -p 'test_*.py' -q
Set-Location microduck-studio; uv run pytest -q
Set-Location ..; git diff --check
```

- [x] **Step 4: 自审**

重新读取 diff 和所有调用者，确认未改训练仓、未把 synthetic/软件 smoke 写成真机通过、未让缺少 HAT/IMU/camera 证据的状态变成 ready。
