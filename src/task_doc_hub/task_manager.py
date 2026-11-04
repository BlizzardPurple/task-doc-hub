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
        description: str | None = None,
        keywords: list[str] | None = None,
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
        metadata = TaskMetadata(
            jira_key=jira_key,
            title=title_slug or jira_key,
            description=description,
            keywords=keywords or [],
        )
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

    def add_context(
        self, task_id: str, label: str, content: str
    ) -> ToolResponse:
        """Append a labeled context block from a session (FE, BE, etc.)."""
        folder = self._resolve_task_folder(task_id)
        if not folder:
            return ToolResponse(
                success=False,
                message=f"Task '{task_id}' not found.",
                error_code=ErrorCode.TASK_NOT_FOUND,
            )
        idx_path = folder / "index.md"
        entry = index_file.append_context(idx_path, label, content)
        return ToolResponse(
            success=True,
            message=f"Context added from [{entry.label}] at {entry.timestamp}.",
            data={
                "timestamp": entry.timestamp,
                "label": entry.label,
            },
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


    def save_recent_screenshots(
        self, task_id: str, count: int = 4
    ) -> ToolResponse:
        """Copy the latest N screenshots from ~/Documents/Screenshots into the task."""
        folder = self._resolve_task_folder(task_id)
        if not folder:
            return ToolResponse(
                success=False,
                message=f"Task '{task_id}' not found.",
                error_code=ErrorCode.TASK_NOT_FOUND,
            )
        stored = screenshot.save_recent_screenshots(folder, count)
        if not stored:
            return ToolResponse(
                success=False,
                message="No screenshots found in ~/Documents/Screenshots.",
                error_code=ErrorCode.NO_SCREENSHOTS_FOUND,
            )
        return ToolResponse(
            success=True,
            message=f"Saved {len(stored)} screenshot(s).",
            data={"filenames": stored, "count": len(stored)},
        )

    def search_tasks(self, query: str) -> ToolResponse:
        """Word-tokenized search across all task metadata, context, and notes.

        Splits the query into words and scores each task by how many words match.
        This means "BEID API external users" will match a task whose description
        contains those words even if they're not contiguous.
        """
        self._ensure_doc_root()
        query_words = [w.lower() for w in query.split() if len(w) >= 2]
        if not query_words:
            return ToolResponse(
                success=True,
                message="Query too short.",
                data={"results": []},
            )

        hits: list[dict] = []
        for idx_path in self.doc_root.glob("*/index.md"):
            try:
                text = idx_path.read_text(encoding="utf-8")
            except OSError:
                continue
            text_lower = text.lower()

            # Score: fraction of query words found in this task
            matched_words = [w for w in query_words if w in text_lower]
            if not matched_words:
                continue

            relevance = len(matched_words) / len(query_words)

            # Extract snippets around the matched words
            snippets: list[str] = []
            for word in matched_words[:3]:  # limit snippet extraction
                snippets.extend(_extract_snippets(text, word, context_chars=60))

            # Also pull title/description from frontmatter for display
            title = None
            description = None
            try:
                meta, _, _ = index_file.read_index(idx_path)
                title = meta.title
                description = meta.description
            except (ValueError, Exception):
                pass

            hits.append(
                SearchHit(
                    task_id=idx_path.parent.name,
                    title=title,
                    description=description,
                    relevance=relevance,
                    snippets=snippets[:5],
                ).model_dump()
            )

        # Sort by relevance descending
        hits.sort(key=lambda h: h["relevance"], reverse=True)

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
            description = None
            status = "unknown"
            if idx_path.exists():
                try:
                    meta, _, _ = index_file.read_index(idx_path)
                    title = meta.title
                    description = meta.description
                    status = meta.status
                except ValueError:
                    logger.warning("Corrupt index in %s", child.name)
            summaries.append(
                TaskSummary(
                    folder_name=child.name,
                    title=title,
                    description=description,
                    status=status,
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
            meta, ctx_entries, notes = index_file.read_index(idx_path)
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
            context_entries=ctx_entries,
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
