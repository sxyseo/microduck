# Microduck Studio Integrated Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one usable Microduck Studio flow for staged hardware inventory, controlled training/resume planning, run timelines, metric comparison, and responsive PC/mobile operation.

**Architecture:** Extend the existing FastAPI/SQLite workbench and its `runs` records instead of introducing a second scheduler. Store staged component state inside the versioned hardware profile, add only one `run_events` table for the shared timeline, and build commands exclusively from server-owned recipes. Reuse the existing polling UI and browser-native SVG for visualization.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, SQLite, pytest, HTML/CSS/vanilla JavaScript, existing Microduck/mjlab command-line tools.

**Spec:** `docs/superpowers/specs/2026-09-13-microduck-studio-integrated-development-workbench-design.md`

## Global Constraints

- Preserve existing FastAPI, SQLite, static-page, and independent-process architecture.
- Do not add dependencies, queues, microservices, arbitrary Shell execution, native mobile clients, or 3D replay.
- Do not open serial ports, connect to SSH targets, start training, or move hardware in tests.
- Keep hardware motion and configuration writes behind their existing explicit confirmations.
- Store missing telemetry as unavailable; never synthesize numeric zero.
- A checkpoint resume always names a checkpoint and parent run explicitly.
- Use `shell=False`; server code owns every executable and CLI flag.
- Mobile layout may monitor and cancel, but does not expose hardware-motion start controls.

---

### Task 1: Staged hardware capabilities

**Files:**
- Modify: `microduck-studio/microduck_studio/core.py`
- Modify: `microduck-studio/microduck_studio/app.py`
- Modify: `microduck-studio/tests/test_core.py`

**Interfaces:**
- Consumes: the existing `hardware_profiles.data` JSON object and `StudioStore.save_hardware(project_id, data)`.
- Produces: `hardware_stage_summary(data: dict[str, Any]) -> dict[str, Any]`; report fields `hardware.stage_summary` and `hardware.capabilities`; `StudioStore.save_project_settings` and `StudioStore.get_project_settings`.

- [ ] **Step 1: Write a failing staged-hardware behavior test**

```python
def test_partial_hardware_exposes_only_available_debug_capabilities(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("duck", tmp_path)
    store.save_hardware(project["id"], {
        "servos": {"model": "HL-2915", "candidates": ["HL-2915"], "count": 2},
        "components": {
            "controller": {"state": "planned"},
            "servo_bench": {"state": "installed", "model": "HL-2915"},
            "imu": {"state": "owned", "model": "BMI270"},
        },
    })
    hardware = store.report(project["id"])["hardware"]
    assert hardware["capabilities"] == ["servo_bench_debug"]
    assert hardware["stage_summary"]["next_components"] == ["controller", "imu"]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/test_core.py::test_partial_hardware_exposes_only_available_debug_capabilities -q`

Expected: FAIL because the report has no `capabilities` or `stage_summary` field.

- [ ] **Step 3: Implement strict component validation and capability derivation**

```python
COMPONENT_STATES = ("planned", "owned", "installed", "detected", "verified", "failed")
DEBUG_CAPABILITIES = {
    "controller": "controller_debug",
    "servo_bench": "servo_bench_debug",
    "joint_group": "joint_group_debug",
    "imu": "imu_debug",
    "camera": "camera_debug",
    "whole_robot": "whole_robot_debug",
}

def hardware_stage_summary(data: dict[str, Any]) -> dict[str, Any]:
    components = data.get("components", {})
    if not isinstance(components, dict):
        raise ValueError("hardware components must be an object")
    normalized = {}
    capabilities = []
    for name, component in components.items():
        if name not in DEBUG_CAPABILITIES or not isinstance(component, dict):
            raise ValueError("hardware component is invalid")
        state = component.get("state")
        if state not in COMPONENT_STATES:
            raise ValueError("hardware component state is invalid")
        normalized[name] = {**component, "state": state}
        if state in {"installed", "detected", "verified"}:
            capabilities.append(DEBUG_CAPABILITIES[name])
    next_components = [name for name, item in normalized.items() if item["state"] in {"planned", "owned", "failed"}]
    return {"components": normalized, "capabilities": sorted(capabilities), "next_components": sorted(next_components)}
```

Call this validator before `save_hardware` writes the profile. Add its derived fields when serializing the latest hardware profile in `report`; do not duplicate those fields in SQLite.

- [ ] **Step 4: Add invalid-state and optional-component tests**

```python
def test_hardware_rejects_unknown_component_state(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("duck", tmp_path)
    with pytest.raises(ValueError, match="component state"):
        store.save_hardware(project["id"], {
            "servos": {"model": "HL-2915", "candidates": ["HL-2915"]},
            "components": {"camera": {"state": "maybe"}},
        })
```

Run: `uv run pytest tests/test_core.py -k "partial_hardware or unknown_component_state" -q`

Expected: PASS.

- [ ] **Step 5: Write a failing project-settings test**

```python
def test_project_settings_validate_and_persist_dashboard_preferences(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("duck", tmp_path)
    saved = store.save_project_settings(project["id"], {
        "visible_metrics": ["reward", "temperature_c"],
        "alert_thresholds": {"temperature_c": 65.0},
        "execution_target": {"kind": "wsl", "distro": "Ubuntu"},
    })
    reopened = StudioStore(tmp_path / "studio.db")
    assert reopened.get_project_settings(project["id"])["data"] == saved["data"]
    with pytest.raises(ValueError, match="visible metric"):
        store.save_project_settings(project["id"], {"visible_metrics": ["unknown"]})
```

- [ ] **Step 6: Run the settings test and verify RED**

Run: `uv run pytest tests/test_core.py::test_project_settings_validate_and_persist_dashboard_preferences -q`

Expected: FAIL because the project-settings API does not exist.

- [ ] **Step 7: Add the single-row project settings store and routes**

```sql
CREATE TABLE IF NOT EXISTS project_settings (
    project_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Allow only known metric names, finite numeric alert thresholds, and validated `local`/`wsl`/`ssh` execution-target fields. Add `GET` and `PUT /api/projects/{project_id}/settings`; include the saved settings in the project report. A single JSON row is sufficient because settings are current preferences, not experiment evidence.

- [ ] **Step 8: Commit the independently useful capability/configuration model**

```bash
git add microduck-studio/microduck_studio/core.py microduck-studio/microduck_studio/app.py microduck-studio/tests/test_core.py
git commit -m "feat: model staged hardware capabilities"
```

### Task 2: Controlled training recipes and explicit resume lineage

**Files:**
- Modify: `microduck-studio/microduck_studio/core.py`
- Modify: `microduck-studio/microduck_studio/app.py`
- Modify: `microduck-studio/tests/test_core.py`

**Interfaces:**
- Consumes: existing project/hardware/preflight records, `capture_git_snapshot`, `_file_sha256`, `_start_training_run`, `_collect_training_smoke`, and run cancellation.
- Produces: `training_recipes()`, `StudioStore.build_training_plan(...)`, `StudioStore.start_training(...)`, `GET /api/training/recipes`, `POST /api/projects/{id}/training/plan`, and `POST /api/projects/{id}/training/run`.

- [ ] **Step 1: Write a failing recipe plan test**

```python
def test_training_plan_uses_allowlisted_recipe_and_records_effective_config(tmp_path: Path, monkeypatch):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("duck", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "preflight", "success")
    checkout = tmp_path / "microduck_rl"
    checkout.mkdir()
    monkeypatch.setattr("microduck_studio.core.platform_module.system", lambda: "Linux")
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")
    plan = store.build_training_plan(project["id"], checkout, "walk", {
        "num_envs": 64, "max_iterations": 200, "gpu_ids": "[0]", "seed": 7,
    }, target={"kind": "local"})
    assert plan["recipe"] == "walk"
    assert plan["effective_config"]["seed"] == 7
    assert plan["command"][:3] == [plan["uv"], "run", "train"]
    assert "--agent.max-iterations" in plan["command"]
```

The helper creates a confirmed hardware profile and successful preflight using existing public store methods; it patches only executable discovery and platform checks, never `build_training_plan`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/test_core.py::test_training_plan_uses_allowlisted_recipe_and_records_effective_config -q`

Expected: FAIL because `build_training_plan` does not exist.

- [ ] **Step 3: Add the minimal server-owned recipe catalog and validator**

```python
TRAINING_RECIPES = {
    "walk": {
        "task": "Mjlab-Velocity-Flat-MicroDuck",
        "defaults": {"num_envs": 4096, "max_iterations": 3000, "gpu_ids": "[0]", "seed": 42},
        "limits": {"num_envs": (1, 16384), "max_iterations": (1, 50000), "seed": (0, 2_147_483_647)},
    }
}

def training_recipes() -> list[dict[str, Any]]:
    return [{"id": name, "task": item["task"], "defaults": item["defaults"]} for name, item in TRAINING_RECIPES.items()]
```

Reject unknown recipe IDs, unknown parameters, booleans supplied as integers, values outside limits, malformed GPU lists, and invalid run names. Build the direct `uv run train` argument array with explicit booleans and `shell=False` execution.

- [ ] **Step 4: Write a failing explicit-resume test**

```python
def test_resume_requires_explicit_matching_parent_and_checkpoint(tmp_path: Path, monkeypatch):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("duck", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "preflight", "success")
    checkout = tmp_path / "microduck_rl"
    checkout.mkdir()
    monkeypatch.setattr("microduck_studio.core.platform_module.system", lambda: "Linux")
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")
    parent = store.start_run(project["id"], "training")
    checkpoint = checkout / "logs" / "rsl_rl" / "velocity" / "run-a" / "model_100.pt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"checkpoint")
    contract = {
        "task": "Mjlab-Velocity-Flat-MicroDuck", "servo_model": "HL-2915",
        "obs_len": 61, "action_len": 14, "control_hz": 50,
    }
    store.finish_run(parent["id"], "passed", {"training_contract": contract})
    plan = store.build_training_plan(
        project["id"], checkout, "walk", {"num_envs": 64, "max_iterations": 50, "gpu_ids": "[0]", "seed": 7},
        target={"kind": "local"}, parent_run_id=parent["id"], checkpoint=str(checkpoint),
    )
    assert plan["training_provenance"]["parent_run_id"] == parent["id"]
    assert plan["training_provenance"]["checkpoint"]["sha256"] == hashlib.sha256(b"checkpoint").hexdigest()
    assert plan["command"][-6:] == ["--agent.resume", "True", "--agent.load-run", "^run\\-a$", "--agent.load-checkpoint", "^model_100\\.pt$"]
```

- [ ] **Step 5: Run the resume test and verify RED**

Run: `uv run pytest tests/test_core.py::test_resume_requires_explicit_matching_parent_and_checkpoint -q`

Expected: FAIL because the plan does not yet accept or validate parent/checkpoint lineage.

- [ ] **Step 6: Implement resume validation and target wrapping**

For resume, require both fields together; verify the parent belongs to the same project and is `training`/`training_smoke`, the checkpoint is a `.pt` file below the checkout, and the parent contract equals the current contract. Append anchored escaped `--agent.load-run` and `--agent.load-checkpoint` regex arguments.

Target rules:

```python
if target["kind"] == "local":
    command = train_args
elif target["kind"] == "wsl":
    command = [wsl, "-d", distro, "--cd", posix_training_dir, "--", *train_args]
else:
    raise ValueError("remote GPU execution is not enabled in this increment")
```

This increment stores SSH target configuration but returns a clear plan-only reason; it does not pretend remote execution is available before remote checkpoint hashing and status reconciliation exist.

- [ ] **Step 7: Reuse the existing asynchronous training process lifecycle**

Generalize `_start_training_run(project_id, kind)` so `training_smoke` and `training` share one active training slot. `start_training` must persist recipe, target, effective config, hardware profile, training contract, output baseline, and provenance before `Popen`; collector completion uses the existing evaluation/cancellation path and registers every newly created `.pt` checkpoint with SHA-256.

- [ ] **Step 8: Add API boundary tests and run the training slice**

```python
def test_training_plan_api_rejects_unknown_recipe(tmp_path: Path, monkeypatch):
    import microduck_studio.app as app_module
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("duck", tmp_path)
    monkeypatch.setattr(app_module, "store", store)
    body = app_module.TrainingIn(
        training_dir=str(tmp_path), recipe="shell", parameters={}, target={"kind": "local"},
    )
    with pytest.raises(app_module.HTTPException) as exc:
        app_module.training_plan(project["id"], body)
    assert exc.value.status_code == 400
```

Run: `uv run pytest tests/test_core.py -k "training_plan or resume_requires or training_recipe" -q`

Expected: PASS.

- [ ] **Step 9: Commit the controlled training vertical slice**

```bash
git add microduck-studio/microduck_studio/core.py microduck-studio/microduck_studio/app.py microduck-studio/tests/test_core.py
git commit -m "feat: add controlled training and resume plans"
```

### Task 3: Shared run timeline and metric comparison

**Files:**
- Modify: `microduck-studio/microduck_studio/core.py`
- Modify: `microduck-studio/microduck_studio/app.py`
- Modify: `microduck-studio/tests/test_core.py`

**Interfaces:**
- Consumes: `StudioStore.start_run`, `update_run_result`, `finish_run`, `cancel_run`, existing run `result`, and TensorBoard `scalars.csv` artifacts.
- Produces: `StudioStore.list_run_events(run_id, after_sequence=0)`, `StudioStore.compare_runs(project_id, left_id, right_id)`, `GET /api/runs/{id}/events`, and `POST /api/projects/{id}/runs/compare`.

- [ ] **Step 1: Write a failing lifecycle timeline test**

```python
def test_run_timeline_records_start_result_and_finish_in_order(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("duck", tmp_path)
    run = store.start_run(project["id"], "preflight")
    store.update_run_result(run["id"], {"status": "running", "progress": 0.5})
    store.finish_run(run["id"], "passed", {"status": "passed"})
    events = store.list_run_events(run["id"])
    assert [item["type"] for item in events] == ["started", "updated", "finished"]
    assert [item["sequence"] for item in events] == [1, 2, 3]
```

- [ ] **Step 2: Run the timeline test and verify RED**

Run: `uv run pytest tests/test_core.py::test_run_timeline_records_start_result_and_finish_in_order -q`

Expected: FAIL because `run_events` and `list_run_events` do not exist.

- [ ] **Step 3: Add one append-only timeline table and shared hooks**

```sql
CREATE TABLE IF NOT EXISTS run_events (
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    type TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence)
);
```

Implement `_append_run_event` inside the same SQLite transaction as the corresponding run update. Event data contains only compact structured state/progress/metric data; large stdout/stderr remains in the run result.

- [ ] **Step 4: Write a failing run comparison test**

```python
def test_run_comparison_reports_config_and_metric_differences(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("duck", tmp_path)
    left = store.start_run(project["id"], "training")
    right = store.start_run(project["id"], "training")
    store.finish_run(left["id"], "passed", {"effective_config": {"seed": 1}, "metrics": {"reward": 2.0}})
    store.finish_run(right["id"], "passed", {"effective_config": {"seed": 2}, "metrics": {"reward": 3.5}})
    comparison = store.compare_runs(project["id"], left["id"], right["id"])
    assert comparison["config_changes"] == [{"field": "seed", "before": 1, "after": 2}]
    assert comparison["metric_changes"] == [{"field": "reward", "before": 2.0, "after": 3.5, "delta": 1.5}]
```

- [ ] **Step 5: Run the comparison test and verify RED**

Run: `uv run pytest tests/test_core.py::test_run_comparison_reports_config_and_metric_differences -q`

Expected: FAIL because `compare_runs` does not exist.

- [ ] **Step 6: Implement same-project comparison and API routes**

Only compare runs that belong to the requested project. Compare scalar values in `effective_config` and `metrics`; represent unavailable values as `None`, not zero. Reject running records because their result is not stable evidence.

- [ ] **Step 7: Run timeline, comparison, restart, and cancellation tests**

Run: `uv run pytest tests/test_core.py -k "timeline or comparison or restarted or cancelled" -q`

Expected: PASS.

- [ ] **Step 8: Commit observability APIs**

```bash
git add microduck-studio/microduck_studio/core.py microduck-studio/microduck_studio/app.py microduck-studio/tests/test_core.py
git commit -m "feat: add run timeline and comparison"
```

### Task 4: Configurable responsive workbench

**Files:**
- Modify: `microduck-studio/web/index.html`
- Modify: `microduck-studio/tests/test_core.py`
- Modify: `microduck-studio/README.md`

**Interfaces:**
- Consumes: hardware report fields, training recipe/plan/run routes, event polling route, and run comparison route.
- Produces: staged-hardware editor, training/resume form, timeline, browser-native metric visualization, and responsive desktop/tablet/mobile layout.

- [ ] **Step 1: Write a failing frontend contract test**

```python
def test_frontend_exposes_staged_hardware_training_resume_and_timeline():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="hardware-components"' in html
    assert 'id="training-recipe"' in html
    assert 'id="training-parent-run"' in html
    assert 'id="training-checkpoint"' in html
    assert 'id="run-timeline"' in html
    assert 'id="run-compare"' in html
    assert "@media(max-width:700px)" in html.replace(" ", "")
```

- [ ] **Step 2: Run the frontend contract test and verify RED**

Run: `uv run pytest tests/test_core.py::test_frontend_exposes_staged_hardware_training_resume_and_timeline -q`

Expected: FAIL because the controls and breakpoint are absent.

- [ ] **Step 3: Add the minimum responsive controls**

Add a component-state JSON editor to the existing hardware card. Extend the training card with recipe, target, validated numeric parameters, optional parent/checkpoint fields, plan/run/cancel buttons, and a status area. Add two run-ID inputs and a compare button. Load/save visible metrics, alert thresholds, and the default execution target through the project settings API; keep the effective task parameters in every run.

Use existing `.grid` and add:

```css
@media(max-width:700px){
  body{padding:12px}
  .grid{grid-template-columns:1fr}
  button{width:100%;min-height:44px}
  .dangerous-start{display:none}
}
```

Mark hardware-motion start buttons with `dangerous-start`; keep cancel buttons visible. The API remains the real security boundary.

- [ ] **Step 4: Add timeline polling and an SVG sparkline**

Poll `/api/runs/{id}/events?after=<sequence>` through the existing `pollRun` loop and append only unseen events. Draw numeric comparison values with a tiny inline SVG; show `不可用` when a value is `null`.

- [ ] **Step 5: Update README operation boundaries**

Document staged component states, project dashboard settings, local/WSL execution, explicit resume lineage, plan-only SSH target status, timeline/comparison, and mobile restrictions. State that no hardware or training starts without confirmation.

- [ ] **Step 6: Verify frontend behavior and syntax**

Run: `uv run pytest tests/test_core.py -k "frontend" -q`

Run: `C:\Users\abel\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe -e "const fs=require('fs'),vm=require('vm');const s=fs.readFileSync('web/index.html','utf8').match(/<script>([\\s\\S]*?)<\\/script>/)[1];new vm.Script(s);console.log('frontend script syntax ok')"`

Expected: tests PASS and Node prints `frontend script syntax ok`.

- [ ] **Step 7: Commit the responsive UI**

```bash
git add microduck-studio/web/index.html microduck-studio/tests/test_core.py microduck-studio/README.md
git commit -m "feat: add responsive integrated debug workbench"
```

### Task 5: Full verification and requirement audit

**Files:**
- Verify: `docs/superpowers/specs/2026-09-13-microduck-studio-integrated-development-workbench-design.md`
- Verify: `microduck-studio/microduck_studio/core.py`
- Verify: `microduck-studio/microduck_studio/app.py`
- Verify: `microduck-studio/web/index.html`
- Verify: `microduck-studio/tests/test_core.py`

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: fresh proof for the implemented increment and an explicit list of deferred spec items.

- [ ] **Step 1: Run the full Python suite**

Run: `uv run pytest -q`

Expected: all tests PASS with zero failures.

- [ ] **Step 2: Compile Python sources**

Run: `uv run python -m compileall -q microduck_studio`

Expected: exit code 0.

- [ ] **Step 3: Check frontend JavaScript syntax**

Run the bundled-Node command from Task 4.

Expected: `frontend script syntax ok`.

- [ ] **Step 4: Check patch hygiene and inspect the complete diff**

Run: `git diff --check`

Run: `git status --short`

Expected: no whitespace errors; unrelated existing script/artifact changes remain untouched.

- [ ] **Step 5: Audit the approved spec**

Confirm implemented now: staged hardware states/capabilities, server-persisted dashboard configuration, server-owned training recipe, local/WSL target, explicit resume lineage, unified timeline, run comparison, responsive mobile monitoring, and safety boundaries.

Record as later increments: SSH execution with remote checkpoint hashing/status reconciliation, continuous stdout/metric streaming, hardware live-sample ingestion, and 3D replay.

- [ ] **Step 6: Commit any verification-driven corrections**

```bash
git add microduck-studio/README.md microduck-studio/microduck_studio/core.py microduck-studio/microduck_studio/app.py microduck-studio/tests/test_core.py microduck-studio/web/index.html
git commit -m "test: verify integrated Microduck Studio foundation"
```
