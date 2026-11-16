"""Thin wrappers around the glab CLI — adapted from pipelineEditor/pe/gitlab.py."""

from __future__ import annotations

import json
import subprocess
import urllib.parse
from typing import Optional

_TIMEOUT = 30


class GitlabError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: str | None = None) -> str:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise GitlabError(f"Command timed out: {cmd[0]}")
    if result.returncode != 0:
        raise GitlabError((result.stderr or result.stdout).strip())
    return result.stdout


def _encoded(gitlab_path: str) -> str:
    return urllib.parse.quote(gitlab_path, safe="")


def api(path: str, method: str = "GET") -> object:
    out = _run(["glab", "api", "--method", method, path])
    return json.loads(out) if out.strip() else {}


def get_pipeline(gitlab_path: str, pipeline_id: int) -> dict:
    proj = _encoded(gitlab_path)
    return api(f"projects/{proj}/pipelines/{pipeline_id}")


def get_jobs(gitlab_path: str, pipeline_id: int) -> list[dict]:
    proj = _encoded(gitlab_path)
    return api(f"projects/{proj}/pipelines/{pipeline_id}/jobs")


def retry_job(gitlab_path: str, job_id: int) -> dict:
    proj = _encoded(gitlab_path)
    return api(f"projects/{proj}/jobs/{job_id}/retry", method="POST")


def play_job(gitlab_path: str, job_id: int) -> dict:
    proj = _encoded(gitlab_path)
    return api(f"projects/{proj}/jobs/{job_id}/play", method="POST")


def parse_pipeline_url(url: str) -> tuple[str, int]:
    """Parse a GitLab pipeline URL into (gitlab_path, pipeline_id)."""
    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    marker = "/-/pipelines/"
    path = parsed.path
    if marker not in path:
        raise ValueError("Not a pipeline URL (missing /-/pipelines/).")
    project_part, _, tail = path.partition(marker)
    gitlab_path = project_part.strip("/")
    pid_str = tail.strip("/").split("/")[0]
    if not pid_str.isdigit():
        raise ValueError("Could not read pipeline id from URL.")
    return gitlab_path, int(pid_str)


def detect_pipeline_kind(gitlab_path: str) -> str:
    """Detect FE/BE/manifest from the GitLab project path."""
    lp = gitlab_path.lower()
    if "enablement-ui" in lp:
        return "fe"
    if "n1-ads-api" in lp or "n1-ads/" in lp:
        return "be"
    if "n1adsref" in lp:
        return "manifest"
    return "unknown"


def is_auth_error(err: GitlabError) -> bool:
    msg = str(err).lower()
    return any(k in msg for k in ["401", "unauthorized", "invalid_grant", "authentication"])
