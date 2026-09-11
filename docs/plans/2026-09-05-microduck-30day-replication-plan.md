# MicroDuck 30-Day Replication Learning Package Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a reproducible 30-day MicroDuck reinforcement-learning study package with source-reading exercises, experiment records, TensorBoard analysis, publishable article drafts, and a safe path toward ONNX deployment and XiaoZhi integration.

**Architecture:** Keep the upstream repositories unchanged. Add an outer learning package under `docs/microduck-30day/` and small, dependency-light helpers under `tools/microduck_learning/`. The package records commands and observed results, while generated plots and screenshots remain artifacts outside the upstream training source.

**Tech Stack:** Markdown, CSV/JSON, Python 3.12, `uv`, TensorBoard event files, Matplotlib, MuJoCo/Warp, PPO/rsl_rl, ONNX Runtime, Playwright screenshot capture.

---

### Task 1: Create the learning-package structure

**Files:**
- Create: `docs/microduck-30day/README.md`
- Create: `docs/microduck-30day/30-day-plan.md`
- Create: `docs/microduck-30day/source-map.md`
- Create: `docs/microduck-30day/articles/editorial-calendar.md`

**Steps:**

1. Define the three-repository relationship and the learning outcome.
2. Map each day to one bounded code-reading or experiment task.
3. Give every task a reproducible command and an expected observation.
4. Mark future results as hypotheses instead of fabricated results.

### Task 2: Add the first reproducible lesson

**Files:**
- Create: `docs/microduck-30day/articles/day-01-5-iteration-smoke-test.md`
- Create: `docs/microduck-30day/experiments/day-01-lesson-01.md`
- Create: `docs/microduck-30day/experiments/experiment-log.csv`

**Steps:**

1. Record the exact command used for the 5-iteration run.
2. Record the actual run directory, checkpoint, event file, and ONNX artifact.
3. Interpret the observed reward, loss, termination, and exploration curves.
4. State clearly that five iterations validate the pipeline but do not produce a walking policy.

### Task 3: Add source-reading and TensorBoard helpers

**Files:**
- Create: `tools/microduck_learning/README.md`
- Create: `tools/microduck_learning/inspect_velocity_cfg.py`
- Create: `tools/microduck_learning/analyze_tensorboard.py`
- Create: `tools/microduck_learning/run_5_iteration_smoke.sh`

**Steps:**

1. Implement line-numbered configuration section inspection.
2. Implement event-file extraction to CSV and Markdown.
3. Implement a compact Matplotlib plot for article use.
4. Add a one-command smoke-test wrapper without changing upstream code.

### Task 4: Capture visual evidence

**Files:**
- Generate: `output/playwright/tensorboard-day01.png`
- Generate: `docs/microduck-30day/assets/day-01-metrics.png`

**Steps:**

1. Capture the local TensorBoard page with the screenshot workflow.
2. Generate a data-backed metrics plot from the actual event file.
3. Inspect both images before linking them in the article.

### Task 5: Verify the package

**Checks:**

1. Run `python tools/microduck_learning/inspect_velocity_cfg.py --section observations`.
2. Run `uv run python tools/microduck_learning/analyze_tensorboard.py --run-dir <run>`.
3. Run the smoke wrapper with `--dry-run` and confirm its command.
4. Run the existing upstream test suite without modifying source files.

