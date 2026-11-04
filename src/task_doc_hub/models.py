"""Pydantic data models for the Task Doc Hub."""

from __future__ import annotations

from pydantic import BaseModel


class TaskMetadata(BaseModel):
    """Metadata stored in a task's index.md frontmatter."""

    jira_key: str | None = None
    title: str | None = None
    status: str = "active"
    links: list[str] = []


class NoteEntry(BaseModel):
    """A single timestamped note."""

    timestamp: str  # ISO 8601
    content: str


class TaskContext(BaseModel):
    """Full context loaded from a task folder."""

    folder_name: str
    metadata: TaskMetadata
    notes: list[NoteEntry]
    files: list[str]


class TaskSummary(BaseModel):
    """Lightweight task info for listing."""

    folder_name: str
    title: str | None = None
    status: str = "active"


class SearchHit(BaseModel):
    """A search result from a single task."""

    task_id: str
    snippets: list[str]


class ToolResponse(BaseModel):
    """Standardized response from every MCP tool."""

    success: bool
    message: str
    data: dict | None = None
    error_code: str | None = None
