# 证据目录说明

这个目录保存“能证明哪一步已经做过”的文件。原始现场文件只追加、不手改；如果实验失败，也保留失败文件并记录原因。

## 可以在没有硬件时生成的文件

- `onnx-contract-*.json`：证明 ONNX 的输入/输出形状、CPU Runtime 调用和模型 SHA-256；仍不等于真机策略通过。
- `training-lineage-*.json`：把 BAM 文件、ONNX 文件和训练仓库 commit 绑定在一起；`purpose=smoke` 不能上真机。
- `bam-model-*-synthetic*.json`：只证明 BAM 合同和训练 smoke 能加载；`data_provenance` 为 `synthetic`，不能用于真实舵机。
- `board-readonly-report-host*.json`：只证明运行报告脚本能读取当前机器；文件名带 `host` 的报告不能替代 Radxa。

## 必须来自实体硬件的文件

- `servo-a-id1.txt`、`servo-b-id2.txt`：HL-2915 只读探针的完整输出；配合照片和万用表记录。
- `hl2915-bench.csv` 和 `hl2915-bench-summary.json`：两只舵机连续只读记录。
- `hl2915-mixed-60s.txt`：两只 HL-2915 与 ID=200 IMU 的当前版混合总线记录，必须含 `max_stale_run`。
- `board-readonly-report-radxa.json`：在 Radxa Zero 3W 上生成的板卡报告。
- `hat-smoke.json`：官方 Robot HAT 的 I²C `0x18`、临时录音、播放和人工听音确认。
- `media-smoke.json`：在 Radxa 上真实采帧、硬件编码/解码和 WebRTC 元素检查；自检文件不能替代它。
- `bam/raw/*.json`、`bam/processed/`、`bam/hl2915-m6.json`：真实 HL-2915 摆锤数据、处理结果和拟合模型。

## 查看当前进度

```powershell
python tools/microduck_learning/bringup_status.py `
  --servo-a-validation artifacts/servo-a-id1-validation.json `
  --servo-b-validation artifacts/servo-b-id2-validation.json `
  --hat-smoke artifacts/hat-smoke.json `
  --media-smoke artifacts/media-smoke.json `
  --onnx-contract artifacts/onnx-contract-lesson-01-repro.json `
  --training-lineage artifacts/training-lineage-hl2915-candidate.json `
  --json-out artifacts/bringup-status-current.json
```

只有 BAM 合同明确写着 `data_provenance=measured`，训练血缘是干净 commit 生成的正式
`candidate`，并且 S0–S6 有现场证据，才可以把模型带入吊装真机验证。
