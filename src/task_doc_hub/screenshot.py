"""Screenshot file copy with filename deduplication and recent-file lookup."""

from __future__ import annotations

import shutil
from pathlib import Path

from task_doc_hub.config import SCREENSHOT_EXTENSIONS, SCREENSHOTS_SOURCE


def copy_screenshot(task_folder: Path, source_path: Path) -> str:
    """Copy a file into the task's screenshots/ subfolder.

    Deduplicates by appending _1, _2, etc. when a name collision occurs.
    Returns the stored filename.
    """
    dest_dir = task_folder / "screenshots"
    stored_name = _deduplicate_filename(dest_dir, source_path.name)
    shutil.copy2(str(source_path), str(dest_dir / stored_name))
    return stored_name


def get_recent_screenshots(count: int = 4) -> list[Path]:
    """Return the most recent `count` screenshot images from the system screenshots folder.

    Sorted by modification time, newest first. Only includes image files.
    """
    if not SCREENSHOTS_SOURCE.is_dir():
        return []
    images = [
        f for f in SCREENSHOTS_SOURCE.iterdir()
        if f.is_file() and f.suffix.lower() in SCREENSHOT_EXTENSIONS
    ]
    images.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return images[:count]


def save_recent_screenshots(
    task_folder: Path, count: int = 4
) -> list[str]:
    """Copy the latest `count` screenshots into the task's screenshots/ folder.

    Returns the list of stored filenames.
    """
    recent = get_recent_screenshots(count)
    stored: list[str] = []
    for src in recent:
        name = copy_screenshot(task_folder, src)
        stored.append(name)
    return stored


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
