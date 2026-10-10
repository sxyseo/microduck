"""Local adapter for the Microduck-kissqy training console.

The browser talks only to Microduck Studio. The one-run training token and the
upstream console's API remain on the local service side of this adapter.
"""
from __future__ import annotations

import ipaddress
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_URL = "http://127.0.0.1:8092"
ALLOWED_QUEUE_ACTIONS = {"start", "pause", "stop", "retry"}
JOB_ID = re.compile(r"^[a-f0-9]{16}$")
REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
TASK_ID = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


class TrainingServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _loopback_origin(value: str) -> tuple[str, str]:
    try:
        parsed = urllib.parse.urlsplit(value)
        host = (parsed.hostname or "").lower()
        port = parsed.port if parsed.port is not None else (80 if parsed.scheme == "http" else 443)
    except ValueError as exc:
        raise ValueError("训练台地址格式无效") from exc
    if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"}:
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if parsed.scheme != "http" or not is_loopback:
            raise ValueError("训练台连接仅允许 HTTP loopback 地址")
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("训练台地址必须只包含本机服务 origin")
    if not 1 <= port <= 65535:
        raise ValueError("训练台端口无效")
    authority_host = f"[{host}]" if ":" in host else host
    origin = f"http://{authority_host}:{port}"
    return origin, authority_host + ":" + str(port)


class KissqyTrainingService:
    """Backend-to-backend adapter for a loopback Microduck-kissqy console."""

    def __init__(
        self,
        base_url: str | None = None,
        db_path: Path | str | None = None,
        *,
        timeout: float = 3.0,
        opener: Callable[..., Any] | None = None,
    ):
        self.origin, self.authority = _loopback_origin(base_url or DEFAULT_URL)
        self.timeout = timeout
        self.opener = opener or urllib.request.urlopen
        self.db_path = Path(db_path) if db_path else None
        if self.db_path:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS kissqy_queue_requests (
                        project_id TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        entry_id TEXT,
                        payload TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY(project_id, request_id)
                    );
                    CREATE TABLE IF NOT EXISTS kissqy_job_links (
                        project_id TEXT NOT NULL,
                        job_id TEXT NOT NULL,
                        entry_id TEXT,
                        task_id TEXT,
                        label TEXT,
                        linked_at TEXT NOT NULL,
                        PRIMARY KEY(project_id, job_id)
                    );
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path:
            raise RuntimeError("训练服务记录库未配置")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _open(self, path: str, *, method: str = "GET", payload: dict | None = None,
              token: str | None = None, accept: str = "application/json"):
        headers = {
            "Host": self.authority,
            "Origin": self.origin,
            "Accept": accept,
            "Cache-Control": "no-store",
        }
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, allow_nan=False).encode("utf-8")
        if token:
            headers["X-Training-Token"] = token
        request = urllib.request.Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            return self.opener(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            content = exc.read(16_384).decode("utf-8", "replace")
            try:
                body = json.loads(content)
                message = body.get("error") or body.get("detail") or "训练服务请求失败"
            except (ValueError, AttributeError):
                message = "训练服务请求失败"
            if exc.code == 404:
                message = "训练服务暂不提供此接口；版本差异仅影响该功能。"
            raise TrainingServiceError(str(message), exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TrainingServiceError("无法连接本机训练服务，请确认 Microduck-kissqy 训练台正在运行。") from exc

    @staticmethod
    def _read_json(response) -> dict:
        try:
            value = json.loads(response.read(8 * 1024 * 1024).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise TrainingServiceError("训练服务返回了无法识别的数据") from exc
        if not isinstance(value, dict):
            raise TrainingServiceError("训练服务返回格式与预期不同")
        return value

    def _get(self, path: str) -> dict:
        with self._open(path) as response:
            return self._read_json(response)

    def _config(self) -> dict:
        config = self._get("/api/config")
        if not isinstance(config.get("token"), str) or not config["token"]:
            raise TrainingServiceError("训练台未提供本次会话凭据，无法执行写入。", 409)
        return config

    def _post(self, path: str, payload: dict) -> dict:
        config = self._config()
        with self._open(path, method="POST", payload=payload, token=config["token"]) as response:
            return self._read_json(response)

    @staticmethod
    def _small_request(value: dict) -> dict:
        request = value.get("request") or {}
        return {
            key: request[key]
            for key in (
                "task", "label", "num_envs", "iterations", "training_action_scale",
                "training_firmware_p", "action_filter", "seed",
            )
            if key in request
        }

    @classmethod
    def _safe_job(cls, job: dict) -> dict:
        metric = job.get("latest_metric") or {}
        return {
            "id": job.get("id"),
            "op": job.get("op"),
            "status": job.get("status"),
            "created": job.get("created"),
            "ended": job.get("ended"),
            "message": job.get("message"),
            "request": cls._small_request(job),
            "progress": job.get("progress"),
            "metric": {key: metric[key] for key in ("iteration", "reward", "episode_length", "fps") if key in metric},
            "checkpoint_count": len(job.get("checkpoints") or []),
            "compatibility_label": job.get("compatibility_label"),
            "target_compatible": job.get("target_compatible"),
        }

    @classmethod
    def _safe_queue_entry(cls, entry: dict, linked_entry_ids: set[str], linked_job_ids: set[str]) -> dict:
        return {
            "id": entry.get("id"),
            "job_id": entry.get("job_id"),
            "client_id": entry.get("client_id"),
            "created": entry.get("created"),
            "status": entry.get("status"),
            "attempt": entry.get("attempt"),
            "message": entry.get("message"),
            "request": cls._small_request(entry),
            "progress": entry.get("progress"),
            "recipe_sha256": entry.get("recipe_sha256"),
            "linked_to_project": entry.get("id") in linked_entry_ids or entry.get("job_id") in linked_job_ids,
        }

    def snapshot(self, project_id: str) -> dict:
        try:
            config = self._get("/api/config")
            state = self._get("/api/state")
            studio = self._get("/api/studio")
            try:
                remote = self._get("/api/remote/state")
            except TrainingServiceError as exc:
                if exc.status_code != 404:
                    raise
                remote = {"status": "unsupported"}
            linked = self._linked(project_id)
            queue = state.get("training_queue") or {}
            linked_entry_ids = {row["entry_id"] for row in linked if row["entry_id"]}
            linked_job_ids = {row["job_id"] for row in linked}
            safe_entries = [
                self._safe_queue_entry(entry, linked_entry_ids, linked_job_ids)
                for entry in queue.get("entries", [])
                if isinstance(entry, dict)
            ]
            safe_jobs = [self._safe_job(job) for job in state.get("jobs", []) if isinstance(job, dict)]
            self._reconcile_links(project_id, safe_entries)
            linked = self._linked(project_id)
            linked_entry_ids = {row["entry_id"] for row in linked if row.get("entry_id")}
            linked_job_ids = {row["job_id"] for row in linked if row.get("job_id")}
            for entry in safe_entries:
                entry["linked_to_project"] = entry.get("id") in linked_entry_ids or entry.get("job_id") in linked_job_ids
            tasks = (studio.get("tasks") or {}).get("tasks", [])
            recipe = studio.get("recipe") or {}
            profile = state.get("profile") or {}
            environment = state.get("environment") or {}
            return {
                "connected": True,
                "endpoint": self.origin,
                "service_version": config.get("version", "版本信息不可用"),
                "release": config.get("release"),
                "platform": config.get("platform"),
                "remote": {key: remote.get(key) for key in ("target", "status", "message") if key in remote},
                "profile": {key: profile.get(key) for key in ("mode", "distro") if key in profile},
                "environment": {key: environment.get(key) for key in ("ready", "status", "message", "revision", "engine") if key in environment},
                "computer_verified": state.get("computer_verified"),
                "target_runtime": state.get("target_runtime") or studio.get("target_runtime"),
                "recipe": {key: recipe.get(key) for key in ("baseline", "purpose", "version", "training_action_scale") if key in recipe},
                "tasks": [
                    {key: task.get(key) for key in ("id", "name", "enabled", "role", "engine") if key in task}
                    for task in tasks if isinstance(task, dict)
                ],
                "queue": {
                    "enabled": bool(queue.get("enabled")),
                    "failure_policy": queue.get("failure_policy"),
                    "message": queue.get("message"),
                    "entries": safe_entries,
                },
                "jobs": safe_jobs,
                "linked_runs": linked,
                "last_checked": datetime.now(timezone.utc).isoformat(),
                "notes": [],
            }
        except TrainingServiceError as exc:
            return {
                "connected": False,
                "endpoint": self.origin,
                "service_version": None,
                "error": str(exc),
                "queue": {"enabled": False, "entries": []},
                "jobs": [],
                "linked_runs": self._linked(project_id),
                "notes": ["Studio 与训练台版本不同不会自动判定不兼容；按实际接口检查结果显示功能可用性。"],
                "last_checked": datetime.now(timezone.utc).isoformat(),
            }

    def _linked(self, project_id: str) -> list[dict]:
        if not self.db_path:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT job_id, entry_id, task_id, label, linked_at FROM kissqy_job_links WHERE project_id=? ORDER BY linked_at DESC",
                (project_id,),
            ).fetchall()
            queued = conn.execute(
                "SELECT request_id, entry_id, payload, created_at FROM kissqy_queue_requests "
                "WHERE project_id=? AND state='queued' ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        result = [dict(row) for row in rows]
        known_entries = {row.get("entry_id") for row in result}
        for row in queued:
            if row["entry_id"] in known_entries:
                continue
            payload = json.loads(row["payload"])
            result.append({
                "job_id": None,
                "entry_id": row["entry_id"],
                "task_id": payload.get("task"),
                "label": payload.get("label"),
                "linked_at": row["created_at"],
                "state": "queued",
            })
        return result

    def _reconcile_links(self, project_id: str, entries: list[dict]) -> None:
        by_client = {entry.get("client_id"): entry for entry in entries if entry.get("client_id")}
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            pending = conn.execute(
                "SELECT request_id, payload FROM kissqy_queue_requests WHERE project_id=? AND state='pending'",
                (project_id,),
            ).fetchall()
            for row in pending:
                entry = by_client.get(row["request_id"])
                if entry:
                    conn.execute(
                        "UPDATE kissqy_queue_requests SET state='queued', entry_id=? WHERE project_id=? AND request_id=?",
                        (entry.get("id"), project_id, row["request_id"]),
                    )
                    payload = json.loads(row["payload"])
                    if entry.get("job_id"):
                        self._save_link(conn, project_id, entry.get("job_id"), entry.get("id"), payload, now)
            payloads = {entry.get("id"): entry for entry in entries}
            for entry in entries:
                if entry.get("job_id") and entry.get("linked_to_project"):
                    self._save_link(conn, project_id, entry["job_id"], entry.get("id"), entry, now)

    @staticmethod
    def _save_link(conn, project_id: str, job_id: str, entry_id: str | None, payload: dict, now: str) -> None:
        request = payload.get("request") if "request" in payload else payload
        conn.execute(
            "INSERT INTO kissqy_job_links(project_id,job_id,entry_id,task_id,label,linked_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(project_id,job_id) DO UPDATE SET entry_id=excluded.entry_id,task_id=excluded.task_id,label=excluded.label",
            (project_id, job_id, entry_id, request.get("task"), request.get("label"), now),
        )

    @staticmethod
    def _validate_queue_payload(value: dict) -> dict:
        request_id = value.get("request_id")
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise ValueError("请求编号无效；刷新页面后再试")
        task = value.get("task")
        if not isinstance(task, str) or not TASK_ID.fullmatch(task):
            raise ValueError("请选择有效的训练任务")
        for key, low, high in (("num_envs", 1, 8192), ("iterations", 1, 409_600_000), ("training_firmware_p", 1, 32)):
            number = value.get(key)
            if type(number) is not int or not low <= number <= high:
                raise ValueError(f"{key} 超出训练服务支持范围")
        scale = value.get("training_action_scale")
        if type(scale) not in (int, float) or scale not in {0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0}:
            raise ValueError("动作系数须为 0.1–1.0 的已登记档位")
        filter_data = value.get("action_filter")
        if not isinstance(filter_data, dict) or type(filter_data.get("enabled")) is not bool:
            raise ValueError("动作滤波设置无效")
        for key in ("head_alpha", "legs_alpha"):
            number = filter_data.get(key)
            if type(number) not in (int, float) or not 0.01 <= number <= 1:
                raise ValueError("动作滤波系数须在 0.01–1 之间")
        label = value.get("label", "").strip() if isinstance(value.get("label", ""), str) else ""
        if len(label) > 60:
            raise ValueError("训练名称最多 60 个字符")
        seed = value.get("seed")
        if seed is not None and (type(seed) is not int or not 0 <= seed <= 2_147_483_647):
            raise ValueError("随机种子范围无效")
        return {
            "task": task,
            "label": label,
            "num_envs": value["num_envs"],
            "iterations": value["iterations"],
            "save_interval": 1000,
            "training_firmware_p": value["training_firmware_p"],
            "training_action_scale": float(scale),
            "action_filter": {"enabled": filter_data["enabled"], "head_alpha": float(filter_data["head_alpha"]), "legs_alpha": float(filter_data["legs_alpha"]), "version": 1},
            "activation": None,
            "pushes": "default",
            "reward_weights": {},
            "learning_rate": None,
            "seed": seed,
            "gamma": None,
            "entropy": None,
            "clip": None,
            "actor_dims": None,
            "critic_dims": None,
            "client_id": request_id,
        }

    def add_to_queue(self, project_id: str, value: dict) -> dict:
        payload = self._validate_queue_payload(value)
        request_id = payload["client_id"]
        with self._connect() as conn:
            old = conn.execute(
                "SELECT state,entry_id FROM kissqy_queue_requests WHERE project_id=? AND request_id=?",
                (project_id, request_id),
            ).fetchone()
            if old and old["state"] == "queued":
                return {"entry_id": old["entry_id"], "duplicate": True}
            if old and old["state"] == "pending":
                self.snapshot(project_id)
                current = conn.execute(
                    "SELECT state,entry_id FROM kissqy_queue_requests WHERE project_id=? AND request_id=?",
                    (project_id, request_id),
                ).fetchone()
                if current["state"] == "queued":
                    return {"entry_id": current["entry_id"], "duplicate": True, "reconciled": True}
                raise RuntimeError("上次添加的结果未确认；已刷新队列且未重发，请先核对训练队列。")
            timestamp = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO kissqy_queue_requests(project_id,request_id,state,payload,created_at) VALUES(?,?,'pending',?,?) "
                "ON CONFLICT(project_id,request_id) DO UPDATE SET state='pending',entry_id=NULL,payload=excluded.payload,created_at=excluded.created_at",
                (project_id, request_id, json.dumps(payload, ensure_ascii=False), timestamp),
            )
        try:
            studio = self._get("/api/studio")
            tasks = ((studio.get("tasks") or {}).get("tasks") or [])
            selected = next((task for task in tasks if task.get("id") == payload["task"]), None)
            if not selected or selected.get("enabled") is not True:
                with self._connect() as conn:
                    conn.execute("UPDATE kissqy_queue_requests SET state='rejected' WHERE project_id=? AND request_id=?", (project_id, request_id))
                raise ValueError("该任务未被当前训练台启用")
            result = self._post("/api/queue/add", payload)
        except TrainingServiceError as exc:
            if exc.status_code < 500:
                with self._connect() as conn:
                    conn.execute("UPDATE kissqy_queue_requests SET state='rejected' WHERE project_id=? AND request_id=?", (project_id, request_id))
                raise
            raise RuntimeError("训练服务未确认添加结果；刷新队列核对后再操作，不会自动重试。") from exc
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            raise RuntimeError("训练服务未确认添加结果；刷新队列核对后再操作，不会自动重试。") from exc
        entry_id = result.get("entry_id")
        if not isinstance(entry_id, str) or not re.fullmatch(r"[a-f0-9]{16}", entry_id):
            raise RuntimeError("训练服务已响应，但队列编号无法确认；请刷新队列核对。")
        with self._connect() as conn:
            conn.execute(
                "UPDATE kissqy_queue_requests SET state='queued',entry_id=? WHERE project_id=? AND request_id=?",
                (entry_id, project_id, request_id),
            )
        return {"entry_id": entry_id, "duplicate": False}

    def control_queue(self, action: str, entry_id: str | None = None, project_id: str | None = None) -> dict:
        if action not in ALLOWED_QUEUE_ACTIONS:
            raise ValueError("不支持的队列操作")
        if project_id:
            current = self.snapshot(project_id)
            if not current.get("connected"):
                raise TrainingServiceError(current.get("error", "训练台离线"), 503)
            entries = current.get("queue", {}).get("entries", [])
            pending_entries = [entry for entry in entries if entry.get("status") in {"waiting", "starting", "running", "stopping"}]
            if action == "start":
                waiting = [entry for entry in entries if entry.get("status") == "waiting"]
                if not waiting or any(not entry.get("linked_to_project") for entry in pending_entries):
                    raise ValueError("队列含有未关联到当前项目的任务；请先在本项目中整理队列")
            elif action == "pause":
                if pending_entries and any(not entry.get("linked_to_project") for entry in pending_entries):
                    raise ValueError("队列含有其他项目的活动任务，不能从当前项目暂停整个训练队列")
            elif action == "stop":
                active = [job for job in current.get("jobs", []) if job.get("op") == "train" and job.get("status") in {"starting", "running", "stopping"}]
                linked_job_ids = {item.get("job_id") for item in current.get("linked_runs", [])}
                if not active or any(job.get("id") not in linked_job_ids for job in active):
                    raise ValueError("活动训练包含未关联到当前项目的运行，不能从此处停止")
            elif action == "retry":
                entry = next((item for item in entries if item.get("id") == entry_id), None)
                if not entry or not entry.get("linked_to_project") or entry.get("status") not in {"failed", "stopped"}:
                    raise ValueError("只能重试当前项目中已停止或失败的队列任务")
        payload: dict[str, Any] = {"action": action}
        if action == "retry":
            if not isinstance(entry_id, str) or not re.fullmatch(r"[a-f0-9]{16}", entry_id):
                raise ValueError("队列任务编号无效")
            payload["entry_id"] = entry_id
        result = self._post("/api/queue/control", payload)
        if result.get("okay") is not True:
            raise TrainingServiceError("训练服务未确认队列操作", 502)
        return result

    def _require_job_link(self, project_id: str, job_id: str) -> None:
        if not JOB_ID.fullmatch(job_id):
            raise ValueError("训练运行编号格式无效")
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM kissqy_job_links WHERE project_id=? AND job_id=?", (project_id, job_id)).fetchone()
        if not row:
            raise KeyError(job_id)

    def job_log(self, project_id: str, job_id: str) -> str:
        self._require_job_link(project_id, job_id)
        path = "/api/log?job=" + urllib.parse.quote(job_id)
        with self._open(path, accept="text/plain") as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raw = raw[-2 * 1024 * 1024:]
        return raw.decode("utf-8", "replace")

    def model_archive(self, project_id: str, job_id: str) -> bytes:
        self._require_job_link(project_id, job_id)
        path = "/api/model.zip?job=" + urllib.parse.quote(job_id)
        with self._open(path, accept="application/zip") as response:
            raw = response.read(200 * 1024 * 1024 + 1)
        if len(raw) > 200 * 1024 * 1024:
            raise TrainingServiceError("策略包超过本地工作台 200 MB 的下载上限", 413)
        if not raw.startswith(b"PK\x03\x04"):
            raise TrainingServiceError("训练服务返回的策略包不是有效 ZIP", 422)
        return raw
