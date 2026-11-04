"""Shared test fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_doc_root(tmp_path: Path) -> Path:
    """Provide a temporary directory as the doc root for tests."""
    doc_root = tmp_path / ".task-docs"
    doc_root.mkdir()
    return doc_root
