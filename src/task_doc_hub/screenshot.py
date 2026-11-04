"""Capture manager — screenshots and screen recordings with time gap detection."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from task_doc_hub.config import (
    CAPTURE_EXTENSIONS,
    IMAGE_EXTENSIONS,
    SCREENSHOTS_SOURCE,
    TIME_GAP_THRESHOLD,
    VIDEO_EXTENSIONS,
)


def copy_screenshot(task_folder: Path, source_path: Path) -> str:
    """Copy a file into the task's screenshots/ subfolder.

    Deduplicates by appending _1, _2, etc. when a name collision occurs.
    Returns the stored filename.
    """
    dest_dir = task_folder / "screenshots"
    stored_name = _deduplicate_filename(dest_dir, source_path.name)
    shutil.copy2(str(source_path), str(dest_dir / stored_name))
    return stored_name


def get_recent_captures(
    count: int = 4,
    media_type: str = "all",
) -> list[Path]:
    """Return the most recent captures from ~/Documents/Screenshots.

    Args:
        count: How many captures to return.
        media_type: "all" (screenshots + recordings), "image", or "video".

    Sorted by modification time, newest first.
    """
    if not SCREENSHOTS_SOURCE.is_dir():
        return []

    if media_type == "image":
        exts = IMAGE_EXTENSIONS
    elif media_type == "video":
        exts = VIDEO_EXTENSIONS
    else:
        exts = CAPTURE_EXTENSIONS

    files = [
        f for f in SCREENSHOTS_SOURCE.iterdir()
        if f.is_file() and f.suffix.lower() in exts
    ]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files[:count]


def detect_time_gaps(files: list[Path]) -> list[dict]:
    """Check for time gaps >= 30 minutes between consecutive captures.

    Files should be sorted newest-first (as returned by get_recent_captures).

    Returns a list of gap info dicts with:
        - before_file, before_time: the newer file
        - after_file, after_time: the older file
        - gap_minutes: time gap in minutes
    """
    if len(files) < 2:
        return []

    gaps: list[dict] = []
    for i in range(len(files) - 1):
        t_newer = files[i].stat().st_mtime
        t_older = files[i + 1].stat().st_mtime
        delta = t_newer - t_older

        if delta >= TIME_GAP_THRESHOLD:
            gaps.append({
                "before_file": files[i].name,
                "before_time": datetime.fromtimestamp(t_newer, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "after_file": files[i + 1].name,
                "after_time": datetime.fromtimestamp(t_older, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "gap_minutes": round(delta / 60),
            })
    return gaps


def build_capture_listing(files: list[Path]) -> list[dict]:
    """Build a listing of captures with index, name, type, and timestamp."""
    listing: list[dict] = []
    for i, f in enumerate(files):
        mtime = f.stat().st_mtime
        suffix = f.suffix.lower()
        listing.append({
            "index": i + 1,
            "name": f.name,
            "type": "video" if suffix in VIDEO_EXTENSIONS else "image",
            "timestamp": datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "path": str(f),
        })
    return listing


def save_captures(
    task_folder: Path, files: list[Path]
) -> list[str]:
    """Copy a list of capture files into the task's screenshots/ folder.

    Returns the list of stored filenames.
    """
    stored: list[str] = []
    for src in files:
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
