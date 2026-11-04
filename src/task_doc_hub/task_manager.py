"""Central task manager — coordinates all CRUD, search, and sync operations."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from task_doc_hub import drive_sync, git_detector, index_file, screenshot, summarizer
from task_doc_hub.config import SUBFOLDERS, TITLE_SLUG_PATTERN, ErrorCode
from task_doc_hub.models import (
    SearchHit,
    TaskContext,
    TaskMetadata,
    TaskSummary,
    ToolResponse,
)

logger = logging.getLogger(__name__)


class TaskManager:
    """Manages task documentation folders and their contents."""

    def __init__(self, doc_root: Path) -> None:
        self.doc_root = doc_root
        self._ensure_doc_root()

    # ── Lifecycle ──────────────────────────────────────

    def _ensure_doc_root(self) -> None:
        if not self.doc_root.exists():
            self.doc_root.mkdir(parents=True, exist_ok=True)
            logger.warning("Doc root created: %s", self.doc_root)

    def _resolve_task_folder(self, task_id: str) -> Path | None:
        folder = self.doc_root / task_id
        return folder if folder.is_dir() else None

    # ── Tools ──────────────────────────────────────────

    def create_task(
        self,
        jira_key: str | None = None,
        title_slug: str | None = None,
    ) -> ToolResponse:
        folder_name = self._derive_folder_name(jira_key, title_slug)
        if folder_name is None:
            return ToolResponse(
                success=False,
                message="Provide a jira_key or title_slug.",
                error_code=ErrorCode.INVALID_INPUT,
            )
        folder = self.doc_root / folder_name
        if folder.exists():
            return ToolResponse(
                success=False,
                message=f"Task folder '{folder_name}' already exists.",
                error_code=ErrorCode.TASK_EXISTS,
            )
        folder.mkdir(parents=True)
        for sub in SUBFOLDERS:
            sub_path = folder / sub
            sub_path.mkdir()
            (sub_path / ".gitkeep").touch()
        metadata = TaskMetadata(jira_key=jira_key, title=title_slug or jira_key)
        index_file.create_index(folder / "index.md", metadata)
        return ToolResponse(
            success=True,
            message=f"Task '{folder_name}' created.",
            data={"folder": folder_name},
        )

    def get_context(
        self,
        task_id: str | None = None,
        cwd: str | None = None,
    ) -> ToolResponse:
        self._ensure_doc_root()
        if task_id:
            return self._load_context(task_id)
        # Auto-detect from git branch
        branch = git_detector.get_current_branch(cwd)
        if not branch:
            return ToolResponse(
                success=False,
                message="Not in a git repository. Provide a task_id.",
                error_code=ErrorCode.NO_BRANCH_MATCH,
            )
        key = git_detector.extract_jira_key(branch)
        if not key:
            return ToolResponse(
                success=False,
                message=f"No JIRA key found in branch '{branch}'. Provide a task_id.",
                error_code=ErrorCode.NO_BRANCH_MATCH,
            )
        folder = self._resolve_task_folder(key)
        if not folder:
            return ToolResponse(
                success=False,
                message=f"No task folder for '{key}'. Create one with create-task.",
                error_code=ErrorCode.TASK_NOT_FOUND,
            )
        return self._load_context(key)

    def add_note(self, task_id: str, content: str) -> ToolResponse:
        folder = self._resolve_task_folder(task_id)
        if not folder:
            return ToolResponse(
                success=False,
                message=f"Task '{task_id}' not found.",
                error_code=ErrorCode.TASK_NOT_FOUND,
            )
        idx_path = folder / "index.md"
        entry = index_file.append_note(idx_path, content)
        return ToolResponse(
            success=True,
            message=f"Note added at {entry.timestamp}.",
            data={"timestamp": entry.timestamp},
        )

    def add_screenshot(self, task_id: str, source_path: str) -> ToolResponse:
        folder = self._resolve_task_folder(task_id)
        if not folder:
            return ToolResponse(
                success=False,
                message=f"Task '{task_id}' not found.",
                error_code=ErrorCode.TASK_NOT_FOUND,
            )
        src = Path(source_path)
        if not src.is_file():
            return ToolResponse(
                success=False,
                message=f"Source file not found: {source_path}",
                error_code=ErrorCode.FILE_NOT_FOUND,
            )
        stored_name = screenshot.copy_screenshot(folder, src)
        return ToolResponse(
            success=True,
            message=f"Screenshot stored as '{stored_name}'.",
            data={"filename": stored_name},
        )

    def search_tasks(self, query: str) -> ToolResponse:
        self._ensure_doc_root()
        hits: list[dict] = []
        query_lower = query.lower()
        for idx_path in self.doc_root.glob("*/index.md"):
            try:
                text = idx_path.read_text(encoding="utf-8")
            except OSError:
                continue
            if query_lower in text.lower():
                snippets = _extract_snippets(text, query_lower)
                hits.append(
                    SearchHit(
                        task_id=idx_path.parent.name, snippets=snippets
                    ).model_dump()
                )
        if not hits:
            return ToolResponse(
                success=True,
                message="No matching tasks found.",
                data={"results": []},
            )
        return ToolResponse(
            success=True,
            message=f"Found {len(hits)} matching task(s).",
            data={"results": hits},
        )

    def list_tasks(self) -> ToolResponse:
        self._ensure_doc_root()
        summaries: list[dict] = []
        for child in sorted(self.doc_root.iterdir()):
            if not child.is_dir() or child.name.startswith("_"):
                continue
            idx_path = child / "index.md"
            title = None
            status = "unknown"
            if idx_path.exists():
                try:
                    meta, _ = index_file.read_index(idx_path)
                    title = meta.title
                    status = meta.status
                except ValueError:
                    logger.warning("Corrupt index in %s", child.name)
            summaries.append(
                TaskSummary(
                    folder_name=child.name, title=title, status=status
                ).model_dump()
            )
        if not summaries:
            return ToolResponse(
                success=True,
                message="No tasks are currently tracked.",
                data={"tasks": []},
            )
        return ToolResponse(
            success=True,
            message=f"{len(summaries)} task(s) tracked.",
            data={"tasks": summaries},
        )

    def sync_to_drive(self, task_id: str | None = None) -> ToolResponse:
        return drive_sync.sync(self.doc_root, task_id)

    def summarize(self, output_path: str | None = None) -> ToolResponse:
        """Generate a SUMMARY.md with all task data rolled up."""
        dest = Path(output_path) if output_path else None
        return summarizer.generate_summary(self.doc_root, output_path=dest)

    # ── Helpers ────────────────────────────────────────

    @staticmethod
    def _derive_folder_name(
        jira_key: str | None, title_slug: str | None
    ) -> str | None:
        if jira_key:
            return jira_key
        if title_slug and re.match(TITLE_SLUG_PATTERN, title_slug):
            return title_slug
        return None

    def _load_context(self, task_id: str) -> ToolResponse:
        folder = self._resolve_task_folder(task_id)
        if not folder:
            return ToolResponse(
                success=False,
                message=f"Task '{task_id}' not found.",
                error_code=ErrorCode.TASK_NOT_FOUND,
            )
        idx_path = folder / "index.md"
        if not idx_path.exists():
            files = [
                str(p.relative_to(folder))
                for p in folder.rglob("*")
                if p.is_file()
            ]
            return ToolResponse(
                success=True,
                message=f"Warning: index.md missing in '{task_id}'. Listing files.",
                data={"folder": task_id, "files": files},
                error_code=ErrorCode.INDEX_CORRUPT,
            )
        try:
            meta, notes = index_file.read_index(idx_path)
        except ValueError:
            files = [
                str(p.relative_to(folder))
                for p in folder.rglob("*")
                if p.is_file()
            ]
            return ToolResponse(
                success=True,
                message=f"Warning: index.md corrupt in '{task_id}'. Listing files.",
                data={"folder": task_id, "files": files},
                error_code=ErrorCode.INDEX_CORRUPT,
            )
        files = [
            str(p.relative_to(folder))
            for p in folder.rglob("*")
            if p.is_file()
        ]
        ctx = TaskContext(
            folder_name=task_id,
            metadata=meta,
            notes=notes,
            files=files,
        )
        return ToolResponse(
            success=True,
            message=f"Context loaded for '{task_id}'.",
            data=ctx.model_dump(),
        )


def _extract_snippets(
    text: str, query_lower: str, context_chars: int = 80
) -> list[str]:
    """Extract text snippets surrounding each occurrence of the query."""
    text_lower = text.lower()
    snippets: list[str] = []
    start = 0
    while True:
        idx = text_lower.find(query_lower, start)
        if idx == -1:
            break
        snip_start = max(0, idx - context_chars)
        snip_end = min(len(text), idx + len(query_lower) + context_chars)
        snippets.append(text[snip_start:snip_end].strip())
        start = idx + 1
    return snippets
