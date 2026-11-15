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
    html = _build_roboplan_html(name, [], [])

    try:
        sheet_id, sheet_url = _upload_as_sheet(token, name, html)
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
    html = _build_roboplan_html(state["name"], state["items"], ROBOPLAN_QUESTIONS)

    try:
        _update_sheet(token, state["sheet_id"], html)
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

def _build_roboplan_html(
    title: str, items: list[dict], questions: list[str]
) -> str:
    """Build an HTML document that Google Drive converts to a multi-table sheet."""
    rows_html = ""
    for i, item in enumerate(items, 1):
        gl = ", ".join(item.get("gitlab_links", []))
        rows_html += (
            f"<tr>"
            f"<td>{i}</td>"
            f"<td>{_esc(item.get('jira_key', ''))}</td>"
            f"<td>{_esc(item.get('description', ''))}</td>"
            f"<td></td>"  # Owner
            f"<td>{_esc(item.get('status', ''))}</td>"
            f"<td></td><td></td>"  # Start/End date
            f"<td>{_esc(item.get('has_fe', ''))}</td>"
            f"<td>{_esc(item.get('has_be', ''))}</td>"
            f"<td>{_esc(gl)}</td>"
            f"<td></td>"  # Deployment Notes
            f"</tr>\n"
        )

    header_cells = "".join(f"<th>{_esc(c)}</th>" for c in ROBOPLAN_COLUMNS)

    # Build questions section
    questions_html = ""
    for item in items:
        jira_key = item.get("jira_key", "")
        desc = item.get("description", "")
        context = item.get("context", [])
        notes = item.get("notes", [])
        links = item.get("links", [])

        ctx_summary = " | ".join(
            f"[{c.get('label', '')}] {c.get('content', '')}" for c in context
        )
        jira_links = [l for l in links if "jira" in l.lower() or "atlassian" in l.lower()]
        gitlab_links = [l for l in links if "gitlab" in l.lower()]

        answers = [
            f"[{jira_key}] {desc}",
            ctx_summary or "—",
            "See tracking table",
            "—",
            f"JIRA: {jira_key} {' '.join(jira_links)} | GitLab: {' '.join(gitlab_links)}",
        ]

        questions_html += f"<h3>{jira_key}</h3>\n"
        for q, a in zip(ROBOPLAN_QUESTIONS, answers):
            questions_html += f"<p><b>{_esc(q)}</b></p>\n<p>{_esc(a)}</p>\n"
        questions_html += "<hr/>\n"

    return f"""<html><body>
<h1>{_esc(title)} — Tracking</h1>
<table border="1">
<tr>{header_cells}</tr>
{rows_html}
</table>
<br/><br/>
<h1>Release Details</h1>
{questions_html if questions_html else "<p><i>No items yet.</i></p>"}
</body></html>"""


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Drive API calls ──────────────────────────────────

def _upload_as_sheet(token: str, name: str, html: str) -> tuple[str, str]:
    """Upload HTML content as a new Google Sheet. Returns (file_id, web_url)."""
    metadata = json.dumps({
        "name": name,
        "mimeType": "application/vnd.google-apps.spreadsheet",
    })

    resp = requests.post(
        f"{DRIVE_UPLOAD_URL}?uploadType=multipart",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "metadata": ("metadata", metadata, "application/json"),
            "file": ("file.html", html.encode("utf-8"), "text/html"),
        },
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Drive upload failed ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    file_id = data["id"]
    url = f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
    return file_id, url


def _update_sheet(token: str, file_id: str, html: str) -> None:
    """Update an existing Google Sheet by re-uploading HTML content."""
    resp = requests.patch(
        f"{DRIVE_UPLOAD_URL}/{file_id}?uploadType=media",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/html",
        },
        data=html.encode("utf-8"),
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Drive update failed ({resp.status_code}): {resp.text[:200]}")
