"""Configuration constants, regex patterns, and error codes."""

from pathlib import Path

DOC_ROOT = Path.home() / "Nrepos" / ".task-docs"

SUBFOLDERS = ["designs", "screenshots", "specs"]

# Regex for JIRA keys like N1AREF-3027, PROJ-123
JIRA_KEY_PATTERN = r"([A-Z][A-Z0-9]+-\d+)"

# Valid title slug: lowercase alphanumeric + hyphens
TITLE_SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


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
