"""Screenshot file copy with filename deduplication."""

from __future__ import annotations

import shutil
from pathlib import Path


def copy_screenshot(task_folder: Path, source_path: Path) -> str:
    """Copy a file into the task's screenshots/ subfolder.

    Deduplicates by appending _1, _2, etc. when a name collision occurs.
    Returns the stored filename.
    """
    dest_dir = task_folder / "screenshots"
    stored_name = _deduplicate_filename(dest_dir, source_path.name)
    shutil.copy2(str(source_path), str(dest_dir / stored_name))
    return stored_name


def _deduplicate_filename(directory: Path, filename: str) -> str:
    """Append a numeric suffix to avoid overwriting existing files."""
    candidate = filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while (directory / candidate).exists():
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate
