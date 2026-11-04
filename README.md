# Task Doc Hub

A local MCP server for persistent, cross-workspace task documentation management.

Organizes `.md` files, screenshots, and specs in per-task folders — accessible from any Kiro workspace via a user-level MCP server registration.

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

Registered as an MCP server in `~/.kiro/settings/mcp.json`. Provides these tools:

| Tool | Description |
|------|-------------|
| `create-task` | Create a new task folder with standardized template |
| `get-context` | Load task context by ID or auto-detect from git branch |
| `resume` | Alias for get-context |
| `add-note` | Append a timestamped note to a task |
| `add-screenshot` | Store a screenshot in a task folder |
| `search-tasks` | Search across all task documentation |
| `list-tasks` | List all tracked tasks with status |
| `sync-to-drive` | Sync task docs to Google Drive |
