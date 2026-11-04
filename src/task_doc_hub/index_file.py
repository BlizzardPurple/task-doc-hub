"""Index.md file manager — create, read, append notes and context blocks."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from task_doc_hub.models import ContextEntry, NoteEntry, TaskMetadata

FRONTMATTER_DELIM = "---"
CONTEXT_HEADER = "## Context"
NOTES_HEADER = "## Notes"


def create_index(path: Path, metadata: TaskMetadata) -> None:
    """Write a new index.md with metadata frontmatter, context section, and notes section."""
    frontmatter = yaml.dump(
        metadata.model_dump(exclude_none=False), default_flow_style=False
    ).strip()
    content = (
        f"{FRONTMATTER_DELIM}\n{frontmatter}\n{FRONTMATTER_DELIM}\n\n"
        f"{CONTEXT_HEADER}\n\n"
        f"{NOTES_HEADER}\n"
    )
    path.write_text(content, encoding="utf-8")


def read_index(path: Path) -> tuple[TaskMetadata, list[ContextEntry], list[NoteEntry]]:
    """Parse an index.md into metadata, context entries, and notes.

    Raises:
        ValueError: If the file cannot be parsed.
    """
    text = path.read_text(encoding="utf-8")
    metadata = _parse_frontmatter(text)
    context = _parse_context(text)
    notes = _parse_notes(text)
    return metadata, context, notes


def append_note(path: Path, content: str) -> NoteEntry:
    """Append a timestamped note to the notes section. Returns the new entry."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = NoteEntry(timestamp=timestamp, content=content)
    note_block = f"\n### {entry.timestamp}\n\n{entry.content}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(note_block)
    return entry


def append_context(path: Path, label: str, content: str) -> ContextEntry:
    """Append a labeled context block to the context section.

    Inserts the block right after '## Context' (before '## Notes').
    Returns the new ContextEntry.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = ContextEntry(timestamp=timestamp, label=label, content=content)
    context_block = f"\n### [{entry.label}] {entry.timestamp}\n\n{entry.content}\n"

    text = path.read_text(encoding="utf-8")
    notes_idx = text.find(NOTES_HEADER)

    if notes_idx != -1:
        # Insert before ## Notes
        updated = text[:notes_idx].rstrip() + "\n" + context_block + "\n" + text[notes_idx:]
    else:
        # No notes section — append at end
        context_idx = text.find(CONTEXT_HEADER)
        if context_idx != -1:
            updated = text + context_block
        else:
            updated = text + f"\n{CONTEXT_HEADER}\n" + context_block

    path.write_text(updated, encoding="utf-8")
    return entry


def update_metadata(path: Path, **updates: str | list[str] | None) -> TaskMetadata:
    """Update specific frontmatter fields and rewrite the file.

    Accepts keyword arguments matching TaskMetadata fields.
    Returns the updated metadata.
    """
    text = path.read_text(encoding="utf-8")
    metadata = _parse_frontmatter(text)
    update_dict = {k: v for k, v in updates.items() if v is not None}
    metadata = metadata.model_copy(update=update_dict)

    # Rebuild frontmatter
    new_fm = yaml.dump(
        metadata.model_dump(exclude_none=False), default_flow_style=False
    ).strip()

    # Find and replace the frontmatter block
    lines = text.split("\n")
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == FRONTMATTER_DELIM:
            end_idx = i
            break
    if end_idx is None:
        raise ValueError("Missing closing frontmatter delimiter")

    rest = "\n".join(lines[end_idx + 1:])
    updated = f"{FRONTMATTER_DELIM}\n{new_fm}\n{FRONTMATTER_DELIM}{rest}"
    path.write_text(updated, encoding="utf-8")
    return metadata


def _parse_frontmatter(text: str) -> TaskMetadata:
    """Extract YAML frontmatter from between --- delimiters."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != FRONTMATTER_DELIM:
        raise ValueError("Missing opening frontmatter delimiter")
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == FRONTMATTER_DELIM:
            end_idx = i
            break
    if end_idx is None:
        raise ValueError("Missing closing frontmatter delimiter")
    yaml_text = "\n".join(lines[1:end_idx])
    data = yaml.safe_load(yaml_text) or {}
    return TaskMetadata(**data)


def _parse_context(text: str) -> list[ContextEntry]:
    """Extract context entries from between '## Context' and '## Notes'."""
    ctx_idx = text.find(CONTEXT_HEADER)
    if ctx_idx == -1:
        return []
    notes_idx = text.find(NOTES_HEADER)
    if notes_idx != -1:
        ctx_section = text[ctx_idx + len(CONTEXT_HEADER) : notes_idx]
    else:
        ctx_section = text[ctx_idx + len(CONTEXT_HEADER) :]

    entries: list[ContextEntry] = []
    current_label: str | None = None
    current_ts: str | None = None
    current_lines: list[str] = []

    for line in ctx_section.split("\n"):
        if line.startswith("### ["):
            # Save previous entry
            if current_ts is not None and current_label is not None:
                entries.append(
                    ContextEntry(
                        timestamp=current_ts,
                        label=current_label,
                        content="\n".join(current_lines).strip(),
                    )
                )
            # Parse "### [FE] 2026-11-04T10:00:00Z"
            bracket_end = line.find("]")
            if bracket_end != -1:
                current_label = line[5:bracket_end]
                current_ts = line[bracket_end + 2:].strip()
            else:
                current_label = "unknown"
                current_ts = line[4:].strip()
            current_lines = []
        elif current_ts is not None:
            current_lines.append(line)

    if current_ts is not None and current_label is not None and current_lines:
        entries.append(
            ContextEntry(
                timestamp=current_ts,
                label=current_label,
                content="\n".join(current_lines).strip(),
            )
        )
    return entries


def _parse_notes(text: str) -> list[NoteEntry]:
    """Extract notes from markdown sections below '## Notes'."""
    notes_idx = text.find(NOTES_HEADER)
    if notes_idx == -1:
        return []
    notes_section = text[notes_idx + len(NOTES_HEADER) :]
    entries: list[NoteEntry] = []
    current_ts: str | None = None
    current_lines: list[str] = []
    for line in notes_section.split("\n"):
        if line.startswith("### "):
            if current_ts is not None:
                entries.append(
                    NoteEntry(
                        timestamp=current_ts,
                        content="\n".join(current_lines).strip(),
                    )
                )
            current_ts = line[4:].strip()
            current_lines = []
        elif current_ts is not None:
            current_lines.append(line)
    if current_ts is not None and current_lines:
        entries.append(
            NoteEntry(
                timestamp=current_ts,
                content="\n".join(current_lines).strip(),
            )
        )
    return entries
