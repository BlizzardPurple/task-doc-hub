"""Pydantic data models for the Task Doc Hub."""

from __future__ import annotations

from pydantic import BaseModel


class TaskMetadata(BaseModel):
    """Metadata stored in a task's index.md frontmatter."""

    jira_key: str | None = None
    title: str | None = None
    description: str | None = None
    keywords: list[str] = []
    status: str = "active"
    links: list[str] = []


class NoteEntry(BaseModel):
    """A single timestamped note."""

    timestamp: str  # ISO 8601
    content: str


class ContextEntry(BaseModel):
    """A session context block — labeled by source (FE, BE, etc.)."""

    timestamp: str  # ISO 8601
    label: str  # e.g. "FE", "BE", "Design", "QA"
    content: str


class TaskContext(BaseModel):
    """Full context loaded from a task folder."""

    folder_name: str
    metadata: TaskMetadata
    notes: list[NoteEntry]
    context_entries: list[ContextEntry] = []
    files: list[str]


class TaskSummary(BaseModel):
    """Lightweight task info for listing."""

    folder_name: str
    title: str | None = None
    description: str | None = None
    status: str = "active"


class SearchHit(BaseModel):
    """A search result from a single task."""

    task_id: str
    title: str | None = None
    description: str | None = None
    relevance: float = 0.0
    snippets: list[str]


class ToolResponse(BaseModel):
    """Standardized response from every MCP tool."""

    success: bool
    message: str
    data: dict | None = None
    error_code: str | None = None
