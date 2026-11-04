"""Git branch detection and JIRA key extraction."""

from __future__ import annotations

import re
import subprocess

from task_doc_hub.config import JIRA_KEY_PATTERN

_jira_re = re.compile(JIRA_KEY_PATTERN)


def get_current_branch(cwd: str | None = None) -> str | None:
    """Read the current git branch name from the working directory.

    Returns None if not in a git repo or on error.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd or ".",
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def extract_jira_key(branch_name: str) -> str | None:
    """Extract the first JIRA key pattern from a branch name.

    Matches patterns like feature/N1AREF-3027-edit-flow or bugfix/PROJ-42.
    """
    match = _jira_re.search(branch_name)
    return match.group(1) if match else None
