"""MCP server entry point — registers all Doc Hub tools."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from task_doc_hub.config import DOC_ROOT, TASK_STATUSES, VERSION
from task_doc_hub.task_manager import TaskManager

mcp = MCPServer(
    "doc-hub",
    version=VERSION,
    instructions=(
        "Doc Hub — persistent task documentation manager. "
        "Also known as: doc hub, task doc hub, task docs. "
        "Use these tools when the user wants to create tasks, add notes, "
        "add session context, search past work, list tasks, generate summaries, "
        "store screenshots, sync to Drive, manage releases, or update task status. "
        f"Valid task statuses: {', '.join(TASK_STATUSES)}."
    ),
)
manager = TaskManager(DOC_ROOT)


# ── Task CRUD ──────────────────────────────────────────


@mcp.tool()
def create_task(
    jira_key: str | None = None,
    title_slug: str | None = None,
    description: str | None = None,
    keywords: list[str] | None = None,
    links: list[str] | None = None,
) -> dict:
    """Create a new task folder with a standardized template.

    Provide a jira_key (e.g. N1AREF-3027) or a title_slug (e.g. edit-flow-e2).
    Optionally add description, keywords, and links (JIRA URLs, GitLab MRs).
    Creates index.md + designs/, screenshots/, specs/ subfolders.
    """
    return manager.create_task(
        jira_key=jira_key,
        title_slug=title_slug,
        description=description,
        keywords=keywords,
        links=links,
    ).model_dump()


@mcp.tool()
def get_context(
    task_id: str | None = None, cwd: str | None = None
) -> dict:
    """Load task context by ID, or auto-detect from the current git branch.

    Supports partial keys: '3027' matches 'N1AREF-3027'.
    Returns metadata, context entries from all sessions, notes, and file listing.
    """
    return manager.get_context(task_id=task_id, cwd=cwd).model_dump()


@mcp.tool()
def resume(
    task_id: str | None = None, cwd: str | None = None
) -> dict:
    """Resume a task session — alias for get_context."""
    return manager.get_context(task_id=task_id, cwd=cwd).model_dump()


# ── Notes & Context ───────────────────────────────────


@mcp.tool()
def add_note(task_id: str, content: str) -> dict:
    """Append a timestamped note to a task's documentation."""
    return manager.add_note(task_id=task_id, content=content).model_dump()


@mcp.tool()
def add_context(task_id: str, label: str, content: str) -> dict:
    """Append session context to a task's shared documentation.

    Label it by session type: FE, BE, Design, QA, etc.
    Example: add_context("3027", "FE", "Implemented edit form with React Query")
    """
    return manager.add_context(
        task_id=task_id, label=label, content=content
    ).model_dump()


# ── Screenshots & Recordings ─────────────────────────


@mcp.tool()
def add_screenshot(task_id: str, file_path: str) -> dict:
    """Store a specific screenshot or recording in a task's screenshots/ folder."""
    return manager.add_screenshot(task_id=task_id, source_path=file_path).model_dump()


@mcp.tool()
def save_recent_captures(
    task_id: str,
    count: int = 4,
    media_type: str = "all",
    force: bool = False,
) -> dict:
    """Save the latest screenshots and/or screen recordings into a task.

    Grabs from ~/Documents/Screenshots. Time gap detection warns if captures
    are > 30 min apart. Use force=True to skip the check.
    media_type: "all", "image", or "video".
    """
    return manager.save_recent_captures(
        task_id=task_id, count=count, media_type=media_type, force=force
    ).model_dump()


# ── Search & List ─────────────────────────────────────


@mcp.tool()
def search_tasks(query: str) -> dict:
    """Search across all task documentation using word-tokenized matching.

    Describe what you're looking for in plain words. Supports partial keys.
    Results ranked by relevance.
    """
    return manager.search_tasks(query=query).model_dump()


@mcp.tool()
def list_tasks() -> dict:
    """List all tracked tasks with title, description, and status."""
    return manager.list_tasks().model_dump()


# ── Status Management ─────────────────────────────────


@mcp.tool()
def update_status(task_id: str, status: str) -> dict:
    """Update a task's status.

    Valid statuses: planning, blocked, in_progress, final_touches,
    release_queue, released.
    """
    return manager.update_status(task_id=task_id, status=status).model_dump()


# ── Release Planner ───────────────────────────────────


@mcp.tool()
def add_to_release_queue(task_id: str) -> dict:
    """Move a task to release_queue and add it to the active roboplan Google Sheet.

    Auto-populates the sheet from the task's doc hub data: description,
    JIRA key, context entries, GitLab links, and inferred FE/BE flags.
    Creates a new roboplan sheet if none exists (named 'Roboplan <Month> <A/B>').
    """
    return manager.add_to_release_queue(task_id=task_id).model_dump()


@mcp.tool()
def finalize_release() -> dict:
    """Mark the current release as done.

    Archives the active roboplan sheet, marks all release_queue tasks as
    'released', and creates a fresh roboplan for the next release cycle.
    """
    return manager.finalize_release().model_dump()


@mcp.tool()
def release_status() -> dict:
    """Get info about the current active release — name, sheet URL, items."""
    return manager.release_status().model_dump()



# ── Pipeline Watcher ──────────────────────────────────


@mcp.tool()
def watch_pipeline(pipeline_url: str) -> dict:
    """Start watching a GitLab pipeline. Polls every 60 seconds.

    FE pipelines: auto-retries 01_install_dependencies up to 4x,
    auto-deploys when all prereqs pass.
    BE/manifest: watch-only, reports status.

    Paste a full GitLab pipeline URL, e.g.:
    https://gitlab.com/group/project/-/pipelines/12345
    """
    from task_doc_hub import pipeline_watcher
    return pipeline_watcher.watch_pipeline(pipeline_url).model_dump()


@mcp.tool()
def unwatch_pipeline(watch_id: int) -> dict:
    """Stop watching a pipeline."""
    from task_doc_hub import pipeline_watcher
    return pipeline_watcher.unwatch_pipeline(watch_id).model_dump()


@mcp.tool()
def pipeline_status(watch_id: int | None = None) -> dict:
    """Get status of watched pipelines.

    Pass a watch_id for a single pipeline, or omit for all.
    Shows status, jobs, retries, elapsed time.
    """
    from task_doc_hub import pipeline_watcher
    return pipeline_watcher.pipeline_status(watch_id).model_dump()

# ── Sync & Summary ────────────────────────────────────


@mcp.tool()
def sync_to_drive(task_id: str | None = None) -> dict:
    """Sync task documentation to Google Drive."""
    return manager.sync_to_drive(task_id=task_id).model_dump()


@mcp.tool()
def summarize(output_path: str | None = None) -> dict:
    """Generate a SUMMARY.md with all tasks rolled up into one shareable file."""
    return manager.summarize(output_path=output_path).model_dump()


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
