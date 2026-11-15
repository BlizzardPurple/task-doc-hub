"""Release planner — manage release queues and roboplan Google Sheets.

Uses the Drive API via clasp OAuth token (no Sheets API scope needed).
Creates spreadsheets by uploading HTML content that Google converts to Sheets.
"""

from __future__ import annotations

import io
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests

from task_doc_hub.config import (
    DOC_ROOT,
    ROBOPLAN_COLUMNS,
    ROBOPLAN_QUESTIONS,
    ErrorCode,
)
from task_doc_hub.google_auth import drive_headers, get_access_token
from task_doc_hub.models import ToolResponse

logger = logging.getLogger(__name__)

RELEASE_STATE_FILE = "_active_release.json"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"


# ── Release naming ────────────────────────────────────

def current_release_name() -> str:
    """Generate release name: 'Roboplan <Month> <A|B>' or from JIRA sprint."""
    sprint = _get_jira_sprint_name()
    if sprint:
        return f"Roboplan {sprint}"
    now = datetime.now(timezone.utc)
    month = now.strftime("%B")
    half = "A" if now.day <= 15 else "B"
    return f"Roboplan {month} {half}"


def _get_jira_sprint_name() -> str | None:
    try:
        result = subprocess.run(
            ["jira", "sprint", "list", "--state", "active", "--plain", "--no-headers"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().split("\n")[0]
            parts = line.split("\t")
            if len(parts) >= 2:
                return parts[1].strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


# ── Release state ─────────────────────────────────────

def _state_path(doc_root: Path) -> Path:
    return doc_root / RELEASE_STATE_FILE


def load_release_state(doc_root: Path) -> dict | None:
    p = _state_path(doc_root)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_release_state(doc_root: Path, state: dict) -> None:
    _state_path(doc_root).write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )


def archive_release_state(doc_root: Path) -> None:
    p = _state_path(doc_root)
    if p.exists():
        state = load_release_state(doc_root)
        if state:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            archive = doc_root / f"_release_archive_{ts}.json"
            archive.write_text(json.dumps(state, indent=2), encoding="utf-8")
        p.unlink()


# ── Google Sheets via Drive API ───────────────────────

def create_roboplan_sheet(
    doc_root: Path,
    release_name: str | None = None,
) -> ToolResponse:
    """Create a new roboplan Google Sheet via Drive API + HTML upload."""
    name = release_name or current_release_name()

    try:
        token = get_access_token()
    except RuntimeError as e:
        return ToolResponse(
            success=False, message=str(e), error_code=ErrorCode.SHEET_ERROR,
        )

    # Build HTML with two tables — Google Sheets converts each <table> reasonably
    csv_content = _build_roboplan_csv([])

    try:
        sheet_id, sheet_url = _upload_as_sheet(token, name, csv_content)
    except RuntimeError as e:
        return ToolResponse(
            success=False, message=str(e), error_code=ErrorCode.SHEET_ERROR,
        )

    state = {
        "name": name,
        "sheet_id": sheet_id,
        "sheet_url": sheet_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "items": [],
    }
    save_release_state(doc_root, state)

    return ToolResponse(
        success=True,
        message=f"Roboplan '{name}' created.",
        data={"sheet_id": sheet_id, "sheet_url": sheet_url, "name": name},
    )


def add_item_to_roboplan(
    doc_root: Path,
    task_id: str,
    task_data: dict,
) -> ToolResponse:
    """Add a task to the active roboplan — rebuilds and re-uploads the sheet."""
    state = load_release_state(doc_root)
    if not state:
        return ToolResponse(
            success=False,
            message="No active release. Create one first.",
            error_code=ErrorCode.RELEASE_NOT_FOUND,
        )

    try:
        token = get_access_token()
    except RuntimeError as e:
        return ToolResponse(
            success=False, message=str(e), error_code=ErrorCode.SHEET_ERROR,
        )

    # Build item from task data
    jira_key = task_data.get("jira_key", task_id)
    description = task_data.get("description") or task_data.get("title", "")
    keywords = task_data.get("keywords", [])
    context_entries = task_data.get("context", [])
    notes = task_data.get("notes", [])
    links = task_data.get("links", [])
    gitlab_links = [l for l in links if "gitlab" in l.lower()]

    context_text = " ".join(c.get("content", "") for c in context_entries).lower()
    all_text = (description + " " + " ".join(keywords) + " " + context_text).lower()
    has_fe = "Yes" if any(w in all_text for w in ["fe", "frontend", "enablement-ui", "react"]) else ""
    has_be = "Yes" if any(w in all_text for w in ["be", "backend", "n1-ads-api", "api", "endpoint"]) else ""

    item = {
        "task_id": task_id,
        "jira_key": jira_key,
        "description": description,
        "status": "release_queue",
        "has_fe": has_fe,
        "has_be": has_be,
        "gitlab_links": gitlab_links,
        "context": context_entries,
        "notes": notes,
        "links": links,
        "keywords": keywords,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    state["items"].append(item)

    # Rebuild the full sheet HTML and re-upload
    csv_content = _build_roboplan_csv(state["items"])

    try:
        _update_sheet(token, state["sheet_id"], csv_content)
    except RuntimeError as e:
        return ToolResponse(
            success=False, message=str(e), error_code=ErrorCode.SHEET_ERROR,
        )

    save_release_state(doc_root, state)

    return ToolResponse(
        success=True,
        message=f"Added '{jira_key}' to roboplan '{state['name']}'.",
        data={
            "sheet_url": state["sheet_url"],
            "jira_key": jira_key,
            "items_count": len(state["items"]),
        },
    )


def finalize_release(doc_root: Path) -> ToolResponse:
    state = load_release_state(doc_root)
    if not state:
        return ToolResponse(
            success=False,
            message="No active release to finalize.",
            error_code=ErrorCode.RELEASE_NOT_FOUND,
        )
    old_name = state["name"]
    old_url = state["sheet_url"]
    archive_release_state(doc_root)
    result = create_roboplan_sheet(doc_root)
    return ToolResponse(
        success=True,
        message=f"Release '{old_name}' finalized. New roboplan created.",
        data={
            "archived_release": old_name,
            "archived_sheet_url": old_url,
            "new_release": result.data if result.success else None,
        },
    )


def get_release_status(doc_root: Path) -> ToolResponse:
    state = load_release_state(doc_root)
    if not state:
        return ToolResponse(
            success=True, message="No active release.", data={"active": False},
        )
    return ToolResponse(
        success=True,
        message=f"Active release: {state['name']} ({len(state['items'])} items).",
        data={
            "active": True,
            "name": state["name"],
            "sheet_url": state["sheet_url"],
            "items": state["items"],
            "created_at": state["created_at"],
        },
    )


# ── HTML builders ─────────────────────────────────────

def _build_roboplan_csv(items: list[dict]) -> str:
    """Build CSV content for the roboplan tracking table + release details."""
    import csv
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(ROBOPLAN_COLUMNS)

    # Tracking rows
    for i, item in enumerate(items, 1):
        gl = " | ".join(item.get("gitlab_links", []))
        writer.writerow([
            i,
            item.get("jira_key", ""),
            item.get("description", ""),
            "",  # Owner
            item.get("status", ""),
            "",  # Start Date
            "",  # End Date
            item.get("has_fe", ""),
            item.get("has_be", ""),
            gl,
            "",  # Deployment Notes
        ])

    # Blank separator rows
    writer.writerow([])
    writer.writerow(["RELEASE DETAILS"])
    writer.writerow([])

    # Release detail questions per item
    for item in items:
        jira_key = item.get("jira_key", "")
        desc = item.get("description", "")
        context = item.get("context", [])
        links = item.get("links", [])

        ctx_summary = " | ".join(
            f"[{c.get('label', '')}] {c.get('content', '')}" for c in context
        )
        gitlab_links = [l for l in links if "gitlab" in l.lower()]

        answers = [
            f"[{jira_key}] {desc}",
            ctx_summary or "—",
            "See tracking table above",
            "—",
            f"JIRA: {jira_key} | GitLab: {' '.join(gitlab_links)}",
        ]

        writer.writerow([f"--- {jira_key} ---"])
        for q, a in zip(ROBOPLAN_QUESTIONS, answers):
            writer.writerow([f"Q: {q}"])
            writer.writerow([f"A: {a}"])
        writer.writerow([])

    return output.getvalue()


# ── Drive API calls ──────────────────────────────────

def _upload_as_sheet(token: str, name: str, csv_content: str) -> tuple[str, str]:
    """Upload CSV content as a new Google Sheet. Returns (file_id, web_url)."""
    metadata = json.dumps({
        "name": name,
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": ["root"],
    })

    resp = requests.post(
        f"{DRIVE_UPLOAD_URL}?uploadType=multipart",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "metadata": ("metadata", metadata, "application/json"),
            "file": ("file.csv", csv_content.encode("utf-8"), "text/csv"),
        },
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Drive upload failed ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    file_id = data["id"]
    url = f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
    return file_id, url


def _update_sheet(token: str, file_id: str, csv_content: str) -> None:
    """Update an existing Google Sheet by re-uploading CSV content."""
    resp = requests.patch(
        f"{DRIVE_UPLOAD_URL}/{file_id}?uploadType=media",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/csv",
        },
        data=csv_content.encode("utf-8"),
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Drive update failed ({resp.status_code}): {resp.text[:200]}")
