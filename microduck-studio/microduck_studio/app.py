from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .core import StudioStore, evaluate_compatibility, list_serial_ports, preflight, task_status_for_result


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web"
DB_PATH = Path(os.environ.get("MICRODUCK_STUDIO_DB", ROOT / "studio.db"))
store = StudioStore(DB_PATH)
app = FastAPI(title="Microduck Studio", version="0.1.0")


class ProjectIn(BaseModel):
    name: str = Field(min_length=1)
    root: str


class HardwareIn(BaseModel):
    data: dict


class BenchIn(BaseModel):
    raw: dict
    required_duration_s: float = Field(default=60, gt=0)


class ProbePlanIn(BaseModel):
    port: str = Field(min_length=1)
    ids: list[int] = Field(min_length=1)
    watch_seconds: int = Field(default=10, gt=0, le=300)
    include_imu: bool = True


class ProbeExecuteIn(ProbePlanIn):
    confirm: bool = False


class BamRecordPlanIn(BaseModel):
    port: str = Field(min_length=1)
    servo_id: int = Field(ge=0, le=199)
    mass_kg: float = Field(gt=0)
    arm_length_m: float = Field(gt=0)
    output_path: str = Field(min_length=1)
    center_raw: int = Field(default=2048, ge=0, le=4095)
    direction: int = Field(default=1)
    arm_mass_kg: float = Field(default=0.0, ge=0)
    kp: int = Field(default=16, ge=1, le=255)
    vin: float = Field(default=12.0, ge=9.0, le=14.0)
    amplitude_deg: float = Field(default=10.0, ge=1.0, le=30.0)
    duration_s: float = Field(default=6.0, ge=2.0, le=30.0)
    hz: float = Field(default=100.0, ge=20.0, le=200.0)
    confirm_motion: bool = False


class BamRecordExecuteIn(BamRecordPlanIn):
    confirm: bool = False


class TrainingSmokeIn(BaseModel):
    training_dir: str = Field(min_length=1)


class TrainingSmokeExecuteIn(TrainingSmokeIn):
    confirm: bool = False


class RunRetryIn(BaseModel):
    confirm: bool = False


class TensorboardIn(BaseModel):
    training_dir: str = Field(min_length=1)
    run_dir: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)


class TensorboardExecuteIn(TensorboardIn):
    confirm: bool = False


class ControllerIn(BaseModel):
    host: str = Field(min_length=1)
    user: str = Field(default="rock", min_length=1)
    port: int = Field(default=22, gt=0, le=65535)


class ControllerExecuteIn(ControllerIn):
    confirm: bool = False


class PolicyInspectIn(BaseModel):
    onnx_path: str = Field(min_length=1)
    manifest_path: str = Field(min_length=1)
    policy_name: str | None = None


class DeploymentPreflightIn(BaseModel):
    onnx_path: str = Field(min_length=1)
    manifest_path: str = Field(min_length=1)
    runtime: dict


class DeploymentPlanIn(BaseModel):
    onnx_path: str = Field(min_length=1)
    manifest_path: str = Field(min_length=1)
    host: str = Field(min_length=1)
    user: str = Field(default="rock", min_length=1)
    port: int = Field(default=22, gt=0, le=65535)


class DeploymentExecuteIn(DeploymentPlanIn):
    confirm: bool = False


class HardwareAcceptanceIn(BaseModel):
    data: dict


class CompatibilityIn(BaseModel):
    hardware: dict
    policy: dict
    runtime: dict


class ArtifactIn(BaseModel):
    path: str
    kind: str = Field(min_length=1)
    run_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class ExperimentIn(BaseModel):
    title: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    variable: str = Field(min_length=1)
    baseline: object
    expected: object
    context: dict = Field(default_factory=dict)


class ExperimentPatch(BaseModel):
    status: str | None = None
    result: object | None = None
    decision: str | None = None
    evidence_refs: list[str] | None = None


class ExperimentCompareIn(BaseModel):
    left_id: str = Field(min_length=1)
    right_id: str = Field(min_length=1)


class CalibrationIn(BaseModel):
    data: dict


class AssemblyIn(BaseModel):
    data: dict


class SupportBundleIn(BaseModel):
    output_path: str | None = None
    confirm: bool = False


class IdentificationIn(BaseModel):
    data: dict


class IssueIn(BaseModel):
    title: str = Field(min_length=1)
    severity: str = "warning"
    status: str = "open"
    symptom: str = Field(min_length=1)
    suspected_causes: list[str] = Field(default_factory=list)
    next_checks: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    resolution: str | None = None


class IssuePatch(BaseModel):
    title: str | None = None
    severity: str | None = None
    status: str | None = None
    symptom: str | None = None
    suspected_causes: list[str] | None = None
    next_checks: list[str] | None = None
    evidence_refs: list[str] | None = None
    resolution: str | None = None


class IssueFromRunIn(BaseModel):
    title: str | None = None


class SourceIn(BaseModel):
    kind: str = Field(min_length=1)
    location: str = Field(min_length=1)
    revision: str | None = None
    license_status: str = "unknown"
    metadata: dict = Field(default_factory=dict)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/projects")
def create_project(body: ProjectIn):
    return store.create_project(body.name, body.root)


@app.get("/api/projects")
def list_projects():
    return {"projects": store.list_projects()}


@app.get("/api/serial-ports")
def serial_ports():
    return {
        "ports": list_serial_ports(),
        "identity_note": "端口列表只表示操作系统可见设备，不代表已经确认舵机型号或接线。",
    }


@app.get("/api/projects/{project_id}/report")
def report(project_id: str):
    try:
        return store.project_report(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.get("/api/projects/{project_id}")
def project(project_id: str):
    value = store.get_project(project_id)
    if not value:
        raise HTTPException(status_code=404, detail="project not found")
    return value


@app.get("/api/projects/{project_id}/search")
def search_project(project_id: str, q: str, limit: int = Query(default=50, ge=1, le=200)):
    try:
        return store.search_project(project_id, q, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/evidence-search")
def search_evidence(
    project_id: str,
    q: str,
    limit: int = Query(default=50, ge=1, le=200),
    record_type: str | None = Query(default=None, alias="type"),
    status: str | None = Query(default=None),
):
    try:
        return store.search_evidence(project_id, q, limit, record_type=record_type, status=status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/evidence/{evidence_id}")
def evidence_detail(project_id: str, evidence_id: str):
    try:
        return store.get_evidence_detail(project_id, evidence_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="evidence not found") from exc


@app.get("/api/projects/{project_id}/next")
def next_task(project_id: str):
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    return {"task": store.next_task(project_id)}


@app.get("/api/projects/{project_id}/report.md")
def report_markdown(project_id: str):
    try:
        return PlainTextResponse(store.project_report_markdown(project_id), media_type="text/markdown")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/projects/{project_id}/support-bundle")
def support_bundle(project_id: str, body: SupportBundleIn):
    try:
        return store.create_support_bundle(
            project_id,
            body.output_path,
            confirm=body.confirm,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/hardware")
def hardware(project_id: str, body: HardwareIn):
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    return store.save_hardware(project_id, body.data)


@app.post("/api/projects/{project_id}/preflight")
def run_preflight(project_id: str):
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    run = store.start_run(project_id, "preflight")
    store.set_task_status(project_id, "preflight", "running")
    result = preflight(project["root"])
    store.finish_run(run["id"], result["status"], result)
    store.set_task_status(project_id, "preflight", task_status_for_result(result["status"]))
    return {**run, "status": result["status"], "result": result}


@app.post("/api/projects/{project_id}/bench/continuous")
def continuous_bench(project_id: str, body: BenchIn):
    try:
        return store.record_continuous_test(project_id, body.raw, body.required_duration_s)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/projects/{project_id}/bench/probe-plan")
def probe_plan(project_id: str, body: ProbePlanIn):
    try:
        return store.build_read_only_probe_plan(
            project_id, body.port, body.ids, body.watch_seconds, include_imu=body.include_imu
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/bench/probe")
def run_probe(project_id: str, body: ProbeExecuteIn):
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return store.start_read_only_probe(
            project_id,
            body.port,
            body.ids,
            body.watch_seconds,
            confirm=body.confirm,
            include_imu=body.include_imu,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/bench/bam-plan")
def bam_record_plan(project_id: str, body: BamRecordPlanIn):
    try:
        return store.build_bam_record_plan(project_id, **body.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/bench/bam")
def run_bam_record(project_id: str, body: BamRecordExecuteIn):
    try:
        return store.start_bam_record(project_id, **body.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/training/smoke-plan")
def training_smoke_plan(project_id: str, body: TrainingSmokeIn):
    try:
        return store.build_training_smoke_plan(project_id, body.training_dir)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/training/smoke")
def run_training_smoke(project_id: str, body: TrainingSmokeExecuteIn):
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return store.start_training_smoke(project_id, body.training_dir, confirm=body.confirm)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/training/tensorboard-plan")
def tensorboard_plan(project_id: str, body: TensorboardIn):
    try:
        return store.build_tensorboard_plan(
            project_id, body.training_dir, body.run_dir, body.output_dir
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/training/tensorboard")
def run_tensorboard(project_id: str, body: TensorboardExecuteIn):
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return store.execute_tensorboard_summary(
            project_id,
            body.training_dir,
            body.run_dir,
            body.output_dir,
            confirm=body.confirm,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}")
def run_status(run_id: str):
    try:
        return store.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    try:
        return store.cancel_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/retry")
def retry_run(run_id: str, body: RunRetryIn):
    try:
        return store.retry_run(run_id, confirm=body.confirm)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/controller/diagnostic-plan")
def controller_diagnostic_plan(project_id: str, body: ControllerIn):
    try:
        return store.build_controller_diagnostic_plan(
            project_id, body.host, body.user, body.port
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/controller/diagnostic")
def run_controller_diagnostic(project_id: str, body: ControllerExecuteIn):
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    if not body.confirm:
        raise HTTPException(status_code=409, detail="explicit confirmation required")
    try:
        return store.execute_controller_diagnostic(
            project_id, body.host, body.user, body.port
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/policy/inspect")
def inspect_policy(project_id: str, body: PolicyInspectIn):
    try:
        return store.inspect_policy_package(
            project_id, body.onnx_path, body.manifest_path, body.policy_name
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/deployment/preflight")
def deployment_preflight(project_id: str, body: DeploymentPreflightIn):
    try:
        return store.deployment_preflight(
            project_id, body.onnx_path, body.manifest_path, body.runtime
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/deployment/plan")
def deployment_plan(project_id: str, body: DeploymentPlanIn):
    try:
        return store.build_deployment_plan(
            project_id,
            body.onnx_path,
            body.manifest_path,
            body.host,
            body.user,
            body.port,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/deployment/execute")
def deployment_execute(project_id: str, body: DeploymentExecuteIn):
    try:
        return store.execute_deployment(
            project_id,
            body.onnx_path,
            body.manifest_path,
            body.host,
            body.user,
            body.port,
            confirm=body.confirm,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/acceptances")
def save_hardware_acceptance(project_id: str, body: HardwareAcceptanceIn):
    try:
        return store.record_hardware_acceptance(project_id, body.data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/compatibility")
def compatibility(project_id: str, body: CompatibilityIn):
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    run = store.start_run(project_id, "compatibility")
    result = evaluate_compatibility(body.hardware, body.policy, body.runtime)
    store.finish_run(run["id"], result["status"], result)
    return {**run, "status": result["status"], "result": result}


@app.post("/api/projects/{project_id}/artifacts")
def artifact(project_id: str, body: ArtifactIn):
    try:
        return store.register_artifact(
            project_id,
            body.path,
            body.kind,
            run_id=body.run_id,
            metadata=body.metadata,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/experiments")
def create_experiment(project_id: str, body: ExperimentIn):
    try:
        return store.create_experiment(project_id, body.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/experiments/{experiment_id}")
def update_experiment(experiment_id: str, body: ExperimentPatch):
    try:
        return store.update_experiment(
            experiment_id,
            {key: value for key, value in body.model_dump().items() if value is not None},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/experiments/{experiment_id}/link-run/{run_id}")
def link_experiment_run(project_id: str, experiment_id: str, run_id: str):
    try:
        return store.link_run_to_experiment(project_id, experiment_id, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/experiments/compare")
def compare_experiments(project_id: str, body: ExperimentCompareIn):
    try:
        return store.compare_experiments(project_id, body.left_id, body.right_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/calibrations")
def save_calibration(project_id: str, body: CalibrationIn):
    try:
        return store.save_calibration(project_id, body.data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/calibrations")
def list_calibrations(project_id: str):
    try:
        return {"calibrations": store.list_calibrations(project_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/projects/{project_id}/assemblies")
def save_assembly(project_id: str, body: AssemblyIn):
    try:
        return store.save_assembly(project_id, body.data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/assemblies")
def list_assemblies(project_id: str):
    try:
        return {"assemblies": store.list_assemblies(project_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/projects/{project_id}/identifications")
def save_identification(project_id: str, body: IdentificationIn):
    try:
        return store.save_identification(project_id, body.data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/identifications")
def list_identifications(project_id: str):
    try:
        return {"identifications": store.list_identifications(project_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/projects/{project_id}/issues")
def create_issue(project_id: str, body: IssueIn):
    try:
        return store.create_issue(project_id, body.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/issues")
def list_issues(project_id: str):
    try:
        return {"issues": store.list_issues(project_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


@app.post("/api/projects/{project_id}/issues/from-run/{run_id}")
def create_issue_from_run(project_id: str, run_id: str, body: IssueFromRunIn):
    try:
        return store.create_issue_from_run(project_id, run_id, body.title)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/issues/{issue_id}/link-run/{run_id}")
def link_issue_run(project_id: str, issue_id: str, run_id: str):
    try:
        return store.link_run_to_issue(project_id, issue_id, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.patch("/api/issues/{issue_id}")
def update_issue(issue_id: str, body: IssuePatch):
    try:
        return store.update_issue(
            issue_id,
            {key: value for key, value in body.model_dump().items() if value is not None},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="issue not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/sources")
def save_source(project_id: str, body: SourceIn):
    try:
        return store.save_source(project_id, body.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/sources")
def list_sources(project_id: str):
    try:
        return {"sources": store.list_sources(project_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
