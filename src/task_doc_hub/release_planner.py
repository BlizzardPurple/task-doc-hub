"""Release planner — manage release queues and roboplan Google Sheets."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from task_doc_hub.config import (
    DOC_ROOT,
    GOOGLE_SCOPES,
    ROBOPLAN_COLUMNS,
    ROBOPLAN_QUESTIONS,
    ErrorCode,
)
from task_doc_hub.models import ToolResponse

logger = logging.getLogger(__name__)

RELEASE_STATE_FILE = "_active_release.json"


# ── Release naming ────────────────────────────────────

def current_release_name() -> str:
    """Generate release name: 'Roboplan <Month> <A|B>'.

    Tries JIRA CLI for active sprint name first.
    Falls back to month + half logic.
    """
    sprint = _get_jira_sprint_name()
    if sprint:
        return f"Roboplan {sprint}"
    now = datetime.now(timezone.utc)
    month = now.strftime("%B")
    half = "A" if now.day <= 15 else "B"
    return f"Roboplan {month} {half}"


def _get_jira_sprint_name() -> str | None:
    """Try to get the active sprint name from JIRA CLI."""
    try:
        result = subprocess.run(
            ["jira", "sprint", "list", "--state", "active", "--plain", "--no-headers"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse: ID  NAME  START  END  STATUS
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
    """Load the active release state, or None if no active release."""
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
    """Move active release state to archive."""
    p = _state_path(doc_root)
    if p.exists():
        state = load_release_state(doc_root)
        if state:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            archive = doc_root / f"_release_archive_{ts}.json"
            archive.write_text(json.dumps(state, indent=2), encoding="utf-8")
        p.unlink()


# ── Google Sheets integration ─────────────────────────

def _get_sheets_service(doc_root: Path):
    """Authenticate and return a Sheets API v4 service object."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = doc_root / "_drive_token.json"
    creds_path = doc_root / "_drive_credentials.json"
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), GOOGLE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"Place your OAuth credentials at {creds_path}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(creds_path), GOOGLE_SCOPES
            )
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return build("sheets", "v4", credentials=creds)


def create_roboplan_sheet(
    doc_root: Path,
    release_name: str | None = None,
) -> ToolResponse:
    """Create a new roboplan Google Sheet with two tabs."""
    name = release_name or current_release_name()

    try:
        service = _get_sheets_service(doc_root)
    except Exception as e:
        return ToolResponse(
            success=False,
            message=f"Google Sheets auth failed: {e}",
            error_code=ErrorCode.SHEET_ERROR,
        )

    try:
        spreadsheet = service.spreadsheets().create(
            body={
                "properties": {"title": name},
                "sheets": [
                    {"properties": {"title": "Tracking", "index": 0}},
                    {"properties": {"title": "Release Details", "index": 1}},
                ],
            }
        ).execute()

        sheet_id = spreadsheet["spreadsheetId"]
        sheet_url = spreadsheet["spreadsheetUrl"]

        # Set up Sheet 1 headers
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="Tracking!A1",
            valueInputOption="RAW",
            body={"values": [ROBOPLAN_COLUMNS]},
        ).execute()

        # Set up Sheet 2 with question labels
        questions_data = []
        for q in ROBOPLAN_QUESTIONS:
            questions_data.append([q])
            questions_data.append([""])  # empty row for answer
            questions_data.append([""])  # spacer

        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="'Release Details'!A1",
            valueInputOption="RAW",
            body={"values": questions_data},
        ).execute()

        # Bold the header row and question labels
        tracking_sheet_id = spreadsheet["sheets"][0]["properties"]["sheetId"]
        details_sheet_id = spreadsheet["sheets"][1]["properties"]["sheetId"]
        _format_headers(service, sheet_id, tracking_sheet_id, details_sheet_id)

        # Save release state
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

    except Exception as e:
        return ToolResponse(
            success=False,
            message=f"Failed to create sheet: {e}",
            error_code=ErrorCode.SHEET_ERROR,
        )


def add_item_to_roboplan(
    doc_root: Path,
    task_id: str,
    task_data: dict,
) -> ToolResponse:
    """Add a task entry to the active roboplan sheet.

    task_data is expected to contain fields from the doc hub task's index.md.
    """
    state = load_release_state(doc_root)
    if not state:
        return ToolResponse(
            success=False,
            message="No active release. Create one first with create_roboplan.",
            error_code=ErrorCode.RELEASE_NOT_FOUND,
        )

    try:
        service = _get_sheets_service(doc_root)
    except Exception as e:
        return ToolResponse(
            success=False,
            message=f"Google Sheets auth failed: {e}",
            error_code=ErrorCode.SHEET_ERROR,
        )

    sheet_id = state["sheet_id"]
    row_num = len(state["items"]) + 1

    # Build the row from task data
    jira_key = task_data.get("jira_key", task_id)
    description = task_data.get("description") or task_data.get("title", "")
    owner = task_data.get("owner", "")
    status = task_data.get("status", "release_queue")
    links = task_data.get("links", [])
    gitlab_links = [l for l in links if "gitlab" in l.lower()]

    # Detect has_fe / has_be from context or keywords
    keywords = task_data.get("keywords", [])
    context_text = " ".join(
        c.get("content", "") for c in task_data.get("context", [])
    ).lower()
    all_text = (description + " " + " ".join(keywords) + " " + context_text).lower()
    has_fe = "Yes" if any(w in all_text for w in ["fe", "frontend", "enablement-ui", "react"]) else ""
    has_be = "Yes" if any(w in all_text for w in ["be", "backend", "n1-ads-api", "api", "endpoint"]) else ""

    row = [
        row_num,                                        # #
        jira_key,                                       # JIRA Key
        description,                                    # Issue Description
        owner,                                          # Owner
        status,                                         # Status
        "",                                             # Start Date
        "",                                             # End Date
        has_fe,                                         # Has FE
        has_be,                                         # Has BE
        ", ".join(gitlab_links) if gitlab_links else "", # GitLab MR
        "",                                             # Deployment Notes
    ]

    try:
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="Tracking!A2",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        # Also update Sheet 2 with task details
        _append_release_details(service, sheet_id, task_data, jira_key)

        # Track in state
        state["items"].append({
            "task_id": task_id,
            "jira_key": jira_key,
            "added_at": datetime.now(timezone.utc).isoformat(),
        })
        save_release_state(doc_root, state)

        return ToolResponse(
            success=True,
            message=f"Added '{jira_key}' to roboplan '{state['name']}'.",
            data={
                "sheet_url": state["sheet_url"],
                "row": row_num,
                "jira_key": jira_key,
            },
        )

    except Exception as e:
        return ToolResponse(
            success=False,
            message=f"Failed to add item: {e}",
            error_code=ErrorCode.SHEET_ERROR,
        )


def finalize_release(doc_root: Path) -> ToolResponse:
    """Mark the current release as done. Archives state, creates a new roboplan."""
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

    # Create the next roboplan
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
    """Get the current active release info."""
    state = load_release_state(doc_root)
    if not state:
        return ToolResponse(
            success=True,
            message="No active release.",
            data={"active": False},
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


# ── Helpers ───────────────────────────────────────────

def _append_release_details(
    service: Any, sheet_id: str, task_data: dict, jira_key: str
) -> None:
    """Append the 5 questions + answers for this task to Sheet 2."""
    description = task_data.get("description") or task_data.get("title", "")
    context_entries = task_data.get("context", [])
    notes = task_data.get("notes", [])
    links = task_data.get("links", [])
    keywords = task_data.get("keywords", [])

    # Build context summary from all session context entries
    context_summary = ""
    for c in context_entries:
        label = c.get("label", "")
        content = c.get("content", "")
        context_summary += f"[{label}] {content}\n"

    # Build notes summary (last 3)
    notes_summary = ""
    for n in notes[-3:]:
        notes_summary += f"- {n.get('content', '')}\n"

    # Infer impacted systems from keywords/context
    all_text = (description + " " + " ".join(keywords) + " " + context_summary).lower()
    systems = []
    if any(w in all_text for w in ["enablement-ui", "fe", "frontend", "react"]):
        systems.append("enablement-ui (FE)")
    if any(w in all_text for w in ["n1-ads-api", "be", "backend", "api"]):
        systems.append("n1-ads-api (BE)")
    if any(w in all_text for w in ["manifest", "n1adsref"]):
        systems.append("n1adsref (Manifest)")

    jira_links = [l for l in links if "jira" in l.lower() or "atlassian" in l.lower()]
    gitlab_links = [l for l in links if "gitlab" in l.lower()]
    if jira_key:
        jira_links.insert(0, jira_key)

    answers = [
        f"[{jira_key}] {description}",                              # What
        context_summary.strip() or notes_summary.strip() or "—",    # Why
        ", ".join(systems) if systems else "—",                      # Systems
        "—",                                                         # Expected outcome (user fills)
        f"JIRA: {', '.join(jira_links)}\nGitLab: {', '.join(gitlab_links)}",  # Links
    ]

    rows: list[list[str]] = []
    rows.append([f"--- {jira_key} ---"])
    rows.append([""])
    for q, a in zip(ROBOPLAN_QUESTIONS, answers):
        rows.append([f"Q: {q}"])
        rows.append([f"A: {a}"])
        rows.append([""])
    rows.append([""])

    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range="'Release Details'!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()


def _format_headers(
    service: Any, sheet_id: str, tracking_id: int, details_id: int
) -> None:
    """Bold the header row on both sheets."""
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": tracking_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": tracking_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
    ]
    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": requests},
        ).execute()
    except Exception:
        pass  # formatting is nice-to-have, don't fail on it
