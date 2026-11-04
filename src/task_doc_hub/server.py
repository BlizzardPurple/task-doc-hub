"""FastMCP server entry point — registers all tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from task_doc_hub.config import DOC_ROOT
from task_doc_hub.task_manager import TaskManager

mcp = FastMCP("task-doc-hub")
manager = TaskManager(DOC_ROOT)


@mcp.tool()
def create_task(
    jira_key: str | None = None,
    title_slug: str | None = None,
    description: str | None = None,
    keywords: list[str] | None = None,
) -> dict:
    """Create a new task folder with a standardized template.

    Provide a jira_key (e.g. N1AREF-3027) or a title_slug (e.g. edit-flow-e2).
    Optionally add a description and keywords for better searchability.
    Creates index.md + designs/, screenshots/, specs/ subfolders.
    """
    return manager.create_task(
        jira_key=jira_key,
        title_slug=title_slug,
        description=description,
        keywords=keywords,
    ).model_dump()


@mcp.tool()
def get_context(
    task_id: str | None = None, cwd: str | None = None
) -> dict:
    """Load task context by ID, or auto-detect from the current git branch.

    If no task_id is given, reads the git branch in cwd and extracts a JIRA key.
    Returns metadata, context entries from all sessions, notes, and file listing.
    """
    return manager.get_context(task_id=task_id, cwd=cwd).model_dump()


@mcp.tool()
def resume(
    task_id: str | None = None, cwd: str | None = None
) -> dict:
    """Resume a task session — alias for get_context."""
    return manager.get_context(task_id=task_id, cwd=cwd).model_dump()


@mcp.tool()
def add_note(task_id: str, content: str) -> dict:
    """Append a timestamped note to a task's documentation.

    The note is added to the task's index.md with an ISO 8601 timestamp.
    """
    return manager.add_note(task_id=task_id, content=content).model_dump()


@mcp.tool()
def add_context(task_id: str, label: str, content: str) -> dict:
    """Append session context to a task's shared documentation.

    Use this to share what was done in one Kiro session (e.g. FE work) so that
    another session (e.g. BE work) can see it. Each context block is labeled
    (FE, BE, Design, QA, etc.) and timestamped.

    Example: add_context("N1AREF-3027", "FE", "Implemented edit form with
    React Query caching, added validation for BEID field")
    """
    return manager.add_context(
        task_id=task_id, label=label, content=content
    ).model_dump()


@mcp.tool()
def add_screenshot(task_id: str, file_path: str) -> dict:
    """Store a screenshot in a task's screenshots/ folder.

    Copies the file at file_path into the task folder. Deduplicates filenames
    automatically if a file with the same name already exists.
    """
    return manager.add_screenshot(task_id=task_id, source_path=file_path).model_dump()


@mcp.tool()
def search_tasks(query: str) -> dict:
    """Search across all task documentation using word-tokenized matching.

    You don't need to remember exact JIRA keys. Describe what you're looking for
    in plain words — e.g. "BEID API external users" or "edit flow caching".
    Searches across titles, descriptions, keywords, context, and notes.
    Results are ranked by relevance (how many query words match).
    """
    return manager.search_tasks(query=query).model_dump()


@mcp.tool()
def list_tasks() -> dict:
    """List all tracked tasks with their title, description, and status."""
    return manager.list_tasks().model_dump()


@mcp.tool()
def sync_to_drive(task_id: str | None = None) -> dict:
    """Sync task documentation to Google Drive.

    Syncs a single task (by task_id) or all tasks if task_id is omitted.
    Requires _drive_credentials.json in the doc root.
    """
    return manager.sync_to_drive(task_id=task_id).model_dump()


@mcp.tool()
def summarize(output_path: str | None = None) -> dict:
    """Generate a SUMMARY.md with all tasks rolled up into one shareable file.

    Creates a comprehensive summary at the doc root (or a custom output_path)
    with status overview, task index table, file inventories, and recent notes.
    Great for sharing in Slack, Drive, or a wiki.
    """
    return manager.summarize(output_path=output_path).model_dump()


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
