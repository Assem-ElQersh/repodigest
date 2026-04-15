"""Output formatters: produce .txt digest and .json from an IngestResult."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import IngestResult

SEPARATOR = "=" * 64


# ---------------------------------------------------------------------------
# Directory tree renderer
# ---------------------------------------------------------------------------

def _build_tree_lines(paths: list[str], root: str) -> list[str]:
    """
    Render a list of file paths as an ASCII directory tree.

    Example output::

        myrepo/
        ├── README.md
        ├── src/
        │   ├── main.py
        │   └── utils.py
        └── tests/
            └── test_main.py
    """
    # Build a nested dict representing directories/files
    tree: dict = {}
    for path in sorted(paths):
        parts = PurePosixPath(path).parts
        node = tree
        for part in parts:
            node = node.setdefault(part, {})

    lines: list[str] = [f"{root}/"]

    def _render(node: dict, prefix: str) -> None:
        items = sorted(node.keys())
        for idx, name in enumerate(items):
            is_last = idx == len(items) - 1
            connector = "└── " if is_last else "├── "
            child = node[name]
            if child:  # directory (has children)
                lines.append(f"{prefix}{connector}{name}/")
                extension = "    " if is_last else "│   "
                _render(child, prefix + extension)
            else:  # file (leaf)
                lines.append(f"{prefix}{connector}{name}")

    _render(tree, "")
    return lines


# ---------------------------------------------------------------------------
# Text formatter
# ---------------------------------------------------------------------------

def to_txt(result: "IngestResult") -> str:
    """
    Render an IngestResult as a single LLM-ready plain-text digest.

    Format mirrors gitingest: about section → directory tree → file contents.
    """
    repo_slug = f"{result.owner}/{result.repo}"
    about = result.about
    lines: list[str] = []

    # --- Header ---
    lines += [
        SEPARATOR,
        f"REPOSITORY: {repo_slug}  [{result.branch}]",
        SEPARATOR,
        "",
    ]

    # --- About ---
    lines += ["ABOUT", "-----"]
    if about.get("description"):
        lines.append(f"Description : {about['description']}")
    if about.get("homepage"):
        lines.append(f"Homepage    : {about['homepage']}")
    if about.get("language"):
        lines.append(f"Language    : {about['language']}")
    if about.get("license"):
        lines.append(f"License     : {about['license']}")
    if about.get("topics"):
        lines.append(f"Topics      : {', '.join(about['topics'])}")

    stats_parts = []
    if about.get("stars") is not None:
        stats_parts.append(f"Stars: {about['stars']:,}")
    if about.get("forks") is not None:
        stats_parts.append(f"Forks: {about['forks']:,}")
    if about.get("watchers") is not None:
        stats_parts.append(f"Watchers: {about['watchers']:,}")
    if about.get("open_issues") is not None:
        stats_parts.append(f"Open issues: {about['open_issues']:,}")
    if stats_parts:
        lines.append("Stats       : " + " | ".join(stats_parts))

    if about.get("created_at"):
        lines.append(f"Created     : {about['created_at']}")
    if about.get("updated_at"):
        lines.append(f"Last updated: {about['updated_at']}")
    if about.get("size_kb") is not None:
        lines.append(f"Size        : {about['size_kb']:,} KB")

    lines.append("")

    # --- Summary ---
    lines += [
        SEPARATOR,
        "SUMMARY",
        SEPARATOR,
        f"Files ingested : {len(result.files):,}",
        f"Files skipped  : {len(result.skipped):,}",
        "",
    ]

    # --- Directory tree ---
    lines += [
        SEPARATOR,
        "DIRECTORY STRUCTURE",
        SEPARATOR,
    ]
    tree_lines = _build_tree_lines(result.tree, result.repo)
    lines += tree_lines
    lines.append("")

    # --- File contents ---
    lines += [
        SEPARATOR,
        "FILES",
        SEPARATOR,
        "",
    ]
    for path in result.tree:
        content = result.files.get(path, "")
        lines += [
            f"{'─' * 4} {path} {'─' * max(0, 56 - len(path))}",
            content,
            "",
        ]

    # --- Skipped files (summary) ---
    if result.skipped:
        lines += [
            SEPARATOR,
            f"SKIPPED FILES ({len(result.skipped)})",
            SEPARATOR,
        ]
        lines += [f"  - {p}" for p in result.skipped]
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

def to_json(result: "IngestResult", indent: int = 2) -> str:
    """Render an IngestResult as pretty-printed JSON."""
    payload = {
        "repository": f"{result.owner}/{result.repo}",
        "branch": result.branch,
        "about": result.about,
        "summary": {
            "files_ingested": len(result.files),
            "files_skipped": len(result.skipped),
        },
        "tree": result.tree,
        "files": result.files,
        "skipped": result.skipped,
    }
    return json.dumps(payload, indent=indent, ensure_ascii=False)


def to_dict(result: "IngestResult") -> dict:
    """Return the IngestResult as a plain Python dict (for API responses)."""
    return json.loads(to_json(result))
