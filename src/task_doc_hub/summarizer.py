"""Summarize all task documentation into a single shareable file."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from task_doc_hub import index_file
from task_doc_hub.models import ToolResponse

SUMMARY_FILENAME = "SUMMARY.md"


def generate_summary(doc_root: Path, output_path: Path | None = None) -> ToolResponse:
    """Generate a comprehensive summary of all tasks into a single markdown file.

    The summary is written to output_path (defaults to doc_root/SUMMARY.md)
    and is designed to be shared — dropped into a Drive folder, attached to
    a Slack thread, or pasted into a wiki.
    """
    dest = output_path or (doc_root / SUMMARY_FILENAME)
    tasks = _collect_all_tasks(doc_root)

    if not tasks:
        return ToolResponse(
            success=True,
            message="No tasks to summarize.",
            data={"tasks": 0},
        )

    lines: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines.append(f"# Task Documentation Summary")
    lines.append(f"")
    lines.append(f"Generated: {now}")
    lines.append(f"Total tasks: {len(tasks)}")
    lines.append("")

    # Status breakdown
    status_counts: dict[str, int] = {}
    for t in tasks:
        s = t["status"]
        status_counts[s] = status_counts.get(s, 0) + 1
    lines.append("## Status Overview")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|--------|-------|")
    for status, count in sorted(status_counts.items()):
        lines.append(f"| {status} | {count} |")
    lines.append("")

    # Quick reference table
    lines.append("## Task Index")
    lines.append("")
    lines.append("| Folder | JIRA Key | Title | Status | Files |")
    lines.append("|--------|----------|-------|--------|-------|")
    for t in tasks:
        jira = t["jira_key"] or "—"
        title = t["title"] or "—"
        lines.append(
            f"| {t['folder']} | {jira} | {title} | {t['status']} | {t['file_count']} |"
        )
    lines.append("")

    # Per-task detail
    lines.append("## Task Details")
    lines.append("")
    for t in tasks:
        lines.append(f"### {t['folder']}")
        lines.append("")
        if t["jira_key"]:
            lines.append(f"**JIRA:** {t['jira_key']}")
        if t["title"]:
            lines.append(f"**Title:** {t['title']}")
        lines.append(f"**Status:** {t['status']}")
        if t["links"]:
            lines.append(f"**Links:** {', '.join(t['links'])}")
        lines.append("")

        # Files inventory
        if t["files"]:
            lines.append("**Files:**")
            for f in t["files"]:
                lines.append(f"- `{f}`")
            lines.append("")

        # Recent notes (last 5)
        if t["notes"]:
            lines.append("**Recent Notes:**")
            lines.append("")
            for note in t["notes"][-5:]:
                lines.append(f"#### {note['timestamp']}")
                lines.append("")
                lines.append(note["content"])
                lines.append("")

        lines.append("---")
        lines.append("")

    dest.write_text("\n".join(lines), encoding="utf-8")

    return ToolResponse(
        success=True,
        message=f"Summary generated with {len(tasks)} task(s) at {dest.name}.",
        data={
            "path": str(dest),
            "tasks": len(tasks),
            "statuses": status_counts,
        },
    )


def _collect_all_tasks(doc_root: Path) -> list[dict]:
    """Gather metadata, notes, and file listings from all task folders."""
    tasks: list[dict] = []
    for child in sorted(doc_root.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        idx_path = child / "index.md"
        meta_dict = {
            "folder": child.name,
            "jira_key": None,
            "title": None,
            "status": "unknown",
            "links": [],
            "notes": [],
            "files": [],
            "file_count": 0,
        }

        if idx_path.exists():
            try:
                meta, notes = index_file.read_index(idx_path)
                meta_dict["jira_key"] = meta.jira_key
                meta_dict["title"] = meta.title
                meta_dict["status"] = meta.status
                meta_dict["links"] = meta.links
                meta_dict["notes"] = [n.model_dump() for n in notes]
            except ValueError:
                meta_dict["status"] = "corrupt-index"

        files = [
            str(p.relative_to(child))
            for p in child.rglob("*")
            if p.is_file() and p.name != ".gitkeep"
        ]
        meta_dict["files"] = files
        meta_dict["file_count"] = len(files)
        tasks.append(meta_dict)
    return tasks
