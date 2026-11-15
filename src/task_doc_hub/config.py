"""Configuration constants, regex patterns, and error codes."""

from pathlib import Path

VERSION = "1.1.0"

DOC_ROOT = Path.home() / "Nrepos" / ".task-docs"

SCREENSHOTS_SOURCE = Path.home() / "Documents" / "Screenshots"

SUBFOLDERS = ["designs", "screenshots", "specs"]

# Regex for JIRA keys like N1AREF-3027, PROJ-123
JIRA_KEY_PATTERN = r"([A-Z][A-Z0-9]+-\d+)"

# Valid title slug: lowercase alphanumeric + hyphens
TITLE_SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

# Task status flow
TASK_STATUSES = [
    "planning",
    "blocked",
    "in_progress",
    "final_touches",
    "release_queue",
    "released",
]

# Media extensions
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tiff"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".webm", ".mkv", ".avi"}
CAPTURE_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# Time gap threshold (seconds)
TIME_GAP_THRESHOLD = 30 * 60  # 30 minutes

# Google API scopes (Drive + Sheets)
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]

# Roboplan sheet columns (Sheet 1)
ROBOPLAN_COLUMNS = [
    "#",
    "JIRA Key",
    "Issue Description",
    "Owner",
    "Status",
    "Start Date",
    "End Date",
    "Has FE",
    "Has BE",
    "GitLab MR",
    "Deployment Notes",
]

# Roboplan text questions (Sheet 2)
ROBOPLAN_QUESTIONS = [
    "What is the change? (Description of the proposed change)",
    "Why is it required? (Reason of the proposed change)",
    "What applications/systems are impacted?",
    "Expected outcome (After the proposed change is implemented)",
    "Jira Stories & Gitlab Links",
]


class ErrorCode:
    """Machine-readable error identifiers."""

    TASK_EXISTS = "TASK_EXISTS"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    NO_BRANCH_MATCH = "NO_BRANCH_MATCH"
    DRIVE_AUTH_FAILED = "DRIVE_AUTH_FAILED"
    DRIVE_UPLOAD_FAILED = "DRIVE_UPLOAD_FAILED"
    DOC_ROOT_ERROR = "DOC_ROOT_ERROR"
    INDEX_CORRUPT = "INDEX_CORRUPT"
    INVALID_INPUT = "INVALID_INPUT"
    NO_CAPTURES_FOUND = "NO_CAPTURES_FOUND"
    TIME_GAP_DETECTED = "TIME_GAP_DETECTED"
    SHEET_ERROR = "SHEET_ERROR"
    INVALID_STATUS = "INVALID_STATUS"
    RELEASE_NOT_FOUND = "RELEASE_NOT_FOUND"
