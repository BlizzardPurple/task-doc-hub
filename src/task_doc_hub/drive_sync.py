"""Google Drive synchronization — OAuth2 auth, folder management, file upload."""

from __future__ import annotations

import logging
from pathlib import Path

from task_doc_hub.config import ErrorCode
from task_doc_hub.models import ToolResponse

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_FOLDER_NAME = "TaskDocHub"


def sync(doc_root: Path, task_id: str | None = None) -> ToolResponse:
    """Sync one or all task folders to Google Drive."""
    try:
        service = _get_drive_service(doc_root)
    except Exception as e:
        return ToolResponse(
            success=False,
            message=f"Google Drive authentication failed: {e}. "
            "Re-authenticate by deleting _drive_token.json and rerunning.",
            error_code=ErrorCode.DRIVE_AUTH_FAILED,
        )

    drive_root_id = _ensure_drive_folder(service, DRIVE_FOLDER_NAME)

    if task_id:
        folders = [doc_root / task_id]
        if not folders[0].is_dir():
            return ToolResponse(
                success=False,
                message=f"Task '{task_id}' not found.",
                error_code=ErrorCode.TASK_NOT_FOUND,
            )
    else:
        folders = [
            d for d in sorted(doc_root.iterdir())
            if d.is_dir() and not d.name.startswith("_")
        ]

    errors: list[str] = []
    synced = 0
    for folder in folders:
        task_drive_id = _ensure_drive_folder(
            service, folder.name, parent_id=drive_root_id
        )
        for file_path in folder.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(folder)
            parent_id = _ensure_nested_folders(service, task_drive_id, rel.parent)
            try:
                _upload_or_update(service, parent_id, file_path)
                synced += 1
            except Exception as e:
                errors.append(f"{file_path.name}: {e}")
                logger.error("Upload failed for %s: %s", file_path, e)

    if errors:
        return ToolResponse(
            success=True,
            message=f"Synced {synced} file(s) with {len(errors)} error(s).",
            data={"synced": synced, "errors": errors},
            error_code=ErrorCode.DRIVE_UPLOAD_FAILED,
        )
    return ToolResponse(
        success=True,
        message=f"Synced {synced} file(s) to Google Drive.",
        data={"synced": synced},
    )


def _get_drive_service(doc_root: Path):
    """Authenticate and return a Drive API service object."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = doc_root / "_drive_token.json"
    creds_path = doc_root / "_drive_credentials.json"
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"Place your OAuth credentials at {creds_path}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(creds_path), SCOPES
            )
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return build("drive", "v3", credentials=creds)


def _ensure_drive_folder(
    service, name: str, parent_id: str | None = None
) -> str:
    """Find or create a Drive folder. Returns the folder ID."""
    query = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    if parent_id:
        query += f" and '{parent_id}' in parents"
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    metadata: dict = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def _ensure_nested_folders(service, root_id: str, rel_path: Path) -> str:
    """Create nested folder structure in Drive, returning the deepest folder ID."""
    current_id = root_id
    for part in rel_path.parts:
        if part == ".":
            continue
        current_id = _ensure_drive_folder(service, part, parent_id=current_id)
    return current_id


def _upload_or_update(service, parent_id: str, file_path: Path) -> None:
    """Upload a file to Drive, overwriting if it exists."""
    from googleapiclient.http import MediaFileUpload

    query = (
        f"name='{file_path.name}' and '{parent_id}' in parents "
        f"and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id)").execute()
    existing = results.get("files", [])
    media = MediaFileUpload(str(file_path), resumable=True)
    if existing:
        service.files().update(
            fileId=existing[0]["id"], media_body=media
        ).execute()
    else:
        metadata = {"name": file_path.name, "parents": [parent_id]}
        service.files().create(
            body=metadata, media_body=media, fields="id"
        ).execute()
