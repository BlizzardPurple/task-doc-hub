"""Index.md file manager — create, read, and append notes with YAML frontmatter."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from task_doc_hub.models import NoteEntry, TaskMetadata

FRONTMATTER_DELIM = "---"
NOTES_HEADER = "## Notes"


def create_index(path: Path, metadata: TaskMetadata) -> None:
    """Write a new index.md with metadata frontmatter and empty notes section."""
    frontmatter = yaml.dump(
        metadata.model_dump(exclude_none=False), default_flow_style=False
    ).strip()
    content = f"{FRONTMATTER_DELIM}\n{frontmatter}\n{FRONTMATTER_DELIM}\n\n{NOTES_HEADER}\n"
    path.write_text(content, encoding="utf-8")


def read_index(path: Path) -> tuple[TaskMetadata, list[NoteEntry]]:
    """Parse an index.md into metadata and notes.

    Raises:
        ValueError: If the file cannot be parsed.
    """
    text = path.read_text(encoding="utf-8")
    metadata = _parse_frontmatter(text)
    notes = _parse_notes(text)
    return metadata, notes


def append_note(path: Path, content: str) -> NoteEntry:
    """Append a timestamped note to the notes section. Returns the new entry."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = NoteEntry(timestamp=timestamp, content=content)
    note_block = f"\n### {entry.timestamp}\n\n{entry.content}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(note_block)
    return entry


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
