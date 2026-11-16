"""Pipeline watcher — background poller with auto-retry and auto-deploy."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from task_doc_hub import gitlab_api
from task_doc_hub.config import DOC_ROOT, ErrorCode
from task_doc_hub.models import ToolResponse

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds
FE_RETRY_JOB = "01_install_dependencies"
FE_DEPLOY_JOB = "deploy"
FE_MAX_RETRIES = 4
TERMINAL_FAIL = {"failed", "canceled", "cancelled"}
SUCCESS = {"success", "passed"}
SKIPPED = {"skipped"}
EVENTS_FILE = "_watch_events.json"


@dataclass
class WatchedPipeline:
    watch_id: int
    kind: str  # fe, be, manifest, unknown
    gitlab_path: str
    pipeline_id: int
    web_url: str = ""
    status: str = "created"
    jobs: list[dict] = field(default_factory=list)
    retries: int = 0
    deploy_triggered: bool = False
    deployed: bool = False
    added_at: float = field(default_factory=time.time)
    last_refresh: float = 0.0
    error: str = ""


class WatchStore:
    """Thread-safe watch store."""

    def __init__(self):
        self._lock = threading.Lock()
        self._watches: dict[int, WatchedPipeline] = {}
        self._next_id = 1

    def add(self, watch: WatchedPipeline) -> WatchedPipeline:
        with self._lock:
            watch.watch_id = self._next_id
            self._next_id += 1
            self._watches[watch.watch_id] = watch
            return watch

    def remove(self, watch_id: int) -> bool:
        with self._lock:
            return self._watches.pop(watch_id, None) is not None

    def get(self, watch_id: int) -> Optional[WatchedPipeline]:
        with self._lock:
            return self._watches.get(watch_id)

    def all(self) -> list[WatchedPipeline]:
        with self._lock:
            return list(self._watches.values())

    def exists(self, gitlab_path: str, pipeline_id: int) -> bool:
        with self._lock:
            return any(
                w.gitlab_path == gitlab_path and w.pipeline_id == pipeline_id
                for w in self._watches.values()
            )


class PipelinePoller(threading.Thread):
    """Background thread that polls all watched pipelines."""

    def __init__(self, store: WatchStore, doc_root: Path):
        super().__init__(daemon=True)
        self.store = store
        self.doc_root = doc_root
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        # First cycle immediately
        self._cycle()
        waited = 0.0
        while self._running:
            time.sleep(1)
            waited += 1
            if waited >= POLL_INTERVAL:
                waited = 0.0
                self._cycle()

    def _cycle(self):
        watches = self.store.all()
        if not watches:
            return
        for w in watches:
            if not self._running:
                break
            self._refresh_one(w)

    def _refresh_one(self, w: WatchedPipeline):
        try:
            pipeline = gitlab_api.get_pipeline(w.gitlab_path, w.pipeline_id)
            raw_jobs = gitlab_api.get_jobs(w.gitlab_path, w.pipeline_id)
        except gitlab_api.GitlabError as err:
            w.error = str(err)
            if gitlab_api.is_auth_error(err):
                _emit_event(self.doc_root, "auth_expired", w)
            return

        old_status = w.status
        w.status = pipeline.get("status", "")
        w.web_url = pipeline.get("web_url", w.web_url)
        w.jobs = [
            {"id": j.get("id"), "name": j.get("name", ""), "status": j.get("status", ""), "stage": j.get("stage", "")}
            for j in raw_jobs
        ]
        w.last_refresh = time.time()
        w.error = ""

        # FE auto-retry + auto-deploy
        if w.kind == "fe" and not w.deployed:
            self._handle_fe(w)

        # Detect terminal state
        pstatus = (w.status or "").lower()
        if pstatus in {"success", "passed"} and old_status not in {"success", "passed"}:
            if w.deployed or w.kind != "fe":
                _emit_event(self.doc_root, "deployed" if w.deployed else "success", w)
        elif pstatus in TERMINAL_FAIL and old_status not in TERMINAL_FAIL:
            if w.retries >= FE_MAX_RETRIES or w.kind != "fe":
                _emit_event(self.doc_root, "failed", w)

    def _handle_fe(self, w: WatchedPipeline):
        """FE: retry install job up to 4x, auto-deploy when ready."""
        retry_job = next((j for j in w.jobs if j["name"] == FE_RETRY_JOB), None)
        if (
            retry_job
            and retry_job["status"] in TERMINAL_FAIL
            and w.retries < FE_MAX_RETRIES
        ):
            try:
                gitlab_api.retry_job(w.gitlab_path, retry_job["id"])
                w.retries += 1
                _emit_event(self.doc_root, "retry", w, extra=f"Retry {w.retries}/{FE_MAX_RETRIES}")
            except gitlab_api.GitlabError:
                pass
            return

        deploy_job = next((j for j in w.jobs if j["name"] == FE_DEPLOY_JOB), None)
        if not deploy_job or w.deploy_triggered:
            return
        if deploy_job["status"] in SUCCESS:
            w.deployed = True
            _emit_event(self.doc_root, "deployed", w)
            return

        others = [j for j in w.jobs if j["name"] != FE_DEPLOY_JOB]
        all_ok = all(j["status"] in SUCCESS | SKIPPED for j in others)
        any_failed = any(j["status"] in TERMINAL_FAIL for j in others)
        if all_ok and not any_failed and deploy_job["status"] == "manual":
            try:
                gitlab_api.play_job(w.gitlab_path, deploy_job["id"])
                w.deploy_triggered = True
                w.deployed = True
                _emit_event(self.doc_root, "deployed", w)
            except gitlab_api.GitlabError:
                pass


# ── Event emission (for VS Code notifications) ───────

def _emit_event(doc_root: Path, event_type: str, w: WatchedPipeline, extra: str = ""):
    """Append an event to _watch_events.json for the extension to pick up."""
    events_path = doc_root / EVENTS_FILE
    events = []
    if events_path.exists():
        try:
            events = json.loads(events_path.read_text())
        except (json.JSONDecodeError, OSError):
            events = []

    events.append({
        "type": event_type,
        "watch_id": w.watch_id,
        "pipeline_id": w.pipeline_id,
        "kind": w.kind,
        "status": w.status,
        "web_url": w.web_url,
        "message": extra,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    events_path.write_text(json.dumps(events, indent=2), encoding="utf-8")


# ── Singleton manager ─────────────────────────────────

_store = WatchStore()
_poller: PipelinePoller | None = None


def _ensure_poller():
    global _poller
    if _poller is None or not _poller.is_alive():
        _poller = PipelinePoller(_store, DOC_ROOT)
        _poller.start()


def watch_pipeline(pipeline_url: str) -> ToolResponse:
    """Start watching a pipeline by URL."""
    try:
        gitlab_path, pid = gitlab_api.parse_pipeline_url(pipeline_url)
    except ValueError as e:
        return ToolResponse(
            success=False, message=str(e), error_code=ErrorCode.INVALID_INPUT,
        )

    if _store.exists(gitlab_path, pid):
        return ToolResponse(
            success=False,
            message=f"Pipeline #{pid} is already being watched.",
            error_code=ErrorCode.INVALID_INPUT,
        )

    kind = gitlab_api.detect_pipeline_kind(gitlab_path)

    # Fetch initial state
    try:
        pipeline = gitlab_api.get_pipeline(gitlab_path, pid)
    except gitlab_api.GitlabError as e:
        return ToolResponse(
            success=False, message=f"Failed to fetch pipeline: {e}",
            error_code=ErrorCode.INVALID_INPUT,
        )

    w = WatchedPipeline(
        watch_id=0,
        kind=kind,
        gitlab_path=gitlab_path,
        pipeline_id=pid,
        web_url=pipeline.get("web_url", pipeline_url),
        status=pipeline.get("status", "unknown"),
    )
    w = _store.add(w)
    _ensure_poller()

    return ToolResponse(
        success=True,
        message=f"Watching {kind} pipeline #{pid} (status: {w.status}). Polling every {POLL_INTERVAL}s.",
        data={
            "watch_id": w.watch_id,
            "pipeline_id": pid,
            "kind": kind,
            "status": w.status,
            "web_url": w.web_url,
        },
    )


def unwatch_pipeline(watch_id: int) -> ToolResponse:
    if _store.remove(watch_id):
        return ToolResponse(success=True, message=f"Stopped watching #{watch_id}.")
    return ToolResponse(
        success=False, message=f"Watch #{watch_id} not found.",
        error_code=ErrorCode.INVALID_INPUT,
    )


def pipeline_status(watch_id: int | None = None) -> ToolResponse:
    if watch_id:
        w = _store.get(watch_id)
        if not w:
            return ToolResponse(
                success=False, message=f"Watch #{watch_id} not found.",
                error_code=ErrorCode.INVALID_INPUT,
            )
        return ToolResponse(
            success=True,
            message=f"Pipeline #{w.pipeline_id}: {w.status}",
            data=_watch_to_dict(w),
        )

    watches = _store.all()
    if not watches:
        return ToolResponse(
            success=True, message="No pipelines being watched.",
            data={"watches": []},
        )
    return ToolResponse(
        success=True,
        message=f"Watching {len(watches)} pipeline(s).",
        data={"watches": [_watch_to_dict(w) for w in watches]},
    )


def _watch_to_dict(w: WatchedPipeline) -> dict:
    elapsed = int(time.time() - w.added_at)
    since_refresh = int(time.time() - w.last_refresh) if w.last_refresh else None
    return {
        "watch_id": w.watch_id,
        "pipeline_id": w.pipeline_id,
        "kind": w.kind,
        "status": w.status,
        "web_url": w.web_url,
        "retries": w.retries,
        "deployed": w.deployed,
        "elapsed_seconds": elapsed,
        "since_refresh_seconds": since_refresh,
        "jobs": w.jobs,
        "error": w.error,
    }
