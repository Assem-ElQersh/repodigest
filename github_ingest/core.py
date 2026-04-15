"""Core GitHub API fetching logic for github_ingest."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"

BINARY_EXTENSIONS = {
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp", ".tiff",
    # Audio / Video
    ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".avi", ".mov", ".mkv", ".webm",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    # Compiled / binary
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".lib", ".pyc", ".pyo",
    ".class", ".jar", ".wasm",
    # Fonts
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # Documents (binary)
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Databases
    ".db", ".sqlite", ".sqlite3",
    # Misc binary
    ".bin", ".dat", ".lock",
}

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".env",
    "dist", "build", ".next", ".nuxt", "coverage", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox",
}

DEFAULT_MAX_FILE_SIZE = 500 * 1024  # 500 KB in bytes


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class IngestResult:
    owner: str
    repo: str
    branch: str
    about: dict
    tree: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_headers(token: Optional[str] = None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _parse_repo_input(repo_input: str) -> tuple[str, str]:
    """Accept 'owner/repo' or a full GitHub URL and return (owner, repo)."""
    repo_input = repo_input.strip().rstrip("/")
    # Full URL: https://github.com/owner/repo
    match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", repo_input)
    if match:
        return match.group(1), match.group(2)
    # Short form: owner/repo
    parts = repo_input.split("/")
    if len(parts) == 2:
        return parts[0], parts[1]
    raise ValueError(
        f"Cannot parse repo '{repo_input}'. Use 'owner/repo' or a full GitHub URL."
    )


def _is_skippable(path: str) -> bool:
    """Return True if this path should be excluded from ingestion."""
    parts = path.split("/")
    # Skip if any directory component is in the skip list
    for part in parts[:-1]:
        if part in SKIP_DIRS:
            return True
    # Skip binary file extensions
    filename = parts[-1]
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in BINARY_EXTENSIONS


# ---------------------------------------------------------------------------
# Individual fetchers
# ---------------------------------------------------------------------------

def fetch_repo_about(
    owner: str,
    repo: str,
    token: Optional[str] = None,
) -> dict:
    """Fetch repo metadata: description, homepage, topics, stars, forks, watchers."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    response = requests.get(url, headers=_make_headers(token), timeout=30)
    response.raise_for_status()
    data = response.json()
    return {
        "description": data.get("description"),
        "homepage": data.get("homepage"),
        "topics": data.get("topics", []),
        "stars": data.get("stargazers_count"),
        "forks": data.get("forks_count"),
        "watchers": data.get("subscribers_count"),
        "default_branch": data.get("default_branch", "main"),
        "language": data.get("language"),
        "license": (data.get("license") or {}).get("spdx_id"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "size_kb": data.get("size"),
        "open_issues": data.get("open_issues_count"),
        "is_fork": data.get("fork", False),
        "visibility": data.get("visibility"),
    }


def fetch_repo_tree(
    owner: str,
    repo: str,
    sha: str,
    token: Optional[str] = None,
) -> list[dict]:
    """
    Fetch the full recursive file tree for a given commit SHA.
    Returns a list of tree node dicts with at least 'path', 'type', 'size', 'sha'.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{sha}?recursive=1"
    response = requests.get(url, headers=_make_headers(token), timeout=60)
    response.raise_for_status()
    data = response.json()
    if data.get("truncated"):
        # Large repos: GitHub truncates at ~100k nodes; warn but continue
        import warnings
        warnings.warn(
            f"{owner}/{repo}: tree is truncated by GitHub (>100k items). "
            "Some files may be missing.",
            stacklevel=2,
        )
    return [node for node in data.get("tree", []) if node.get("type") == "blob"]


def fetch_blob_content(
    owner: str,
    repo: str,
    blob_sha: str,
    token: Optional[str] = None,
) -> Optional[str]:
    """Fetch a single blob and decode its text content. Returns None for binary data."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/blobs/{blob_sha}"
    response = requests.get(url, headers=_make_headers(token), timeout=30)
    response.raise_for_status()
    data = response.json()
    encoding = data.get("encoding")
    content_raw = data.get("content", "")
    if encoding == "base64":
        raw_bytes = base64.b64decode(content_raw)
        try:
            return raw_bytes.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return None  # binary content
    # plain text (rare but possible)
    return content_raw


def _get_branch_sha(
    owner: str,
    repo: str,
    branch: str,
    token: Optional[str] = None,
) -> str:
    """Resolve a branch name to its latest commit SHA."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/branches/{branch}"
    response = requests.get(url, headers=_make_headers(token), timeout=30)
    response.raise_for_status()
    return response.json()["commit"]["sha"]


# ---------------------------------------------------------------------------
# User-level fetchers
# ---------------------------------------------------------------------------

def fetch_user_repos(
    username: str,
    token: Optional[str] = None,
    repo_type: str = "owner",
    sort: str = "updated",
) -> list[dict]:
    """
    Fetch all public repositories for a GitHub user.

    Parameters
    ----------
    username:
        GitHub username.
    token:
        Optional GitHub PAT.  Required to see your own private repos via the
        ``/user/repos`` endpoint — but that endpoint is not used here; this
        function always targets ``/users/{username}/repos`` which only returns
        public repos.
    repo_type:
        ``"owner"`` (default) — only repos the user created, no forks.
        ``"all"``   — includes forked repos as well.
    sort:
        ``"updated"`` (default), ``"created"``, ``"pushed"``, or ``"full_name"``.

    Returns
    -------
    list[dict]
        Each element is the raw GitHub repo object (same shape as the REST API).
        Useful fields: ``name``, ``full_name``, ``description``, ``html_url``,
        ``stargazers_count``, ``language``, ``fork``, ``updated_at``.
    """
    headers = _make_headers(token)
    repos: list[dict] = []
    page = 1

    while True:
        response = requests.get(
            f"{GITHUB_API}/users/{username}/repos",
            headers=headers,
            params={
                "per_page": 100,
                "page": page,
                "type": repo_type,
                "sort": sort,
            },
            timeout=30,
        )
        response.raise_for_status()
        batch: list[dict] = response.json()

        if not batch:
            break

        repos.extend(batch)
        page += 1

    return repos


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def ingest(
    repo_input: str,
    token: Optional[str] = None,
    branch: Optional[str] = None,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
    on_progress=None,
) -> IngestResult:
    """
    Fetch the full content of a GitHub repository.

    Parameters
    ----------
    repo_input:
        Either ``'owner/repo'`` or a full GitHub URL.
    token:
        Optional GitHub personal access token (increases rate limit to 5000/h).
    branch:
        Branch to ingest. Defaults to the repo's default branch.
    max_file_size:
        Maximum file size in bytes to include. Larger files are skipped.
        Pass ``0`` for no limit (include all files regardless of size).
    on_progress:
        Optional callable ``(current: int, total: int, path: str)`` for progress reporting.

    Returns
    -------
    IngestResult
    """
    owner, repo = _parse_repo_input(repo_input)

    # 1. Repo metadata
    about = fetch_repo_about(owner, repo, token)
    resolved_branch = branch or about["default_branch"]

    # 2. Resolve branch → commit SHA → tree
    commit_sha = _get_branch_sha(owner, repo, resolved_branch, token)
    blob_nodes = fetch_repo_tree(owner, repo, commit_sha, token)

    # 3. Filter nodes
    file_paths = []
    skipped = []
    nodes_to_fetch: list[dict] = []

    for node in blob_nodes:
        path = node["path"]
        size = node.get("size", 0) or 0
        if _is_skippable(path):
            skipped.append(path)
        elif max_file_size > 0 and size > max_file_size:
            skipped.append(path)
        else:
            file_paths.append(path)
            nodes_to_fetch.append(node)

    # 4. Fetch file contents
    files: dict[str, str] = {}
    total = len(nodes_to_fetch)
    for i, node in enumerate(nodes_to_fetch):
        path = node["path"]
        blob_sha = node["sha"]
        if on_progress:
            on_progress(i + 1, total, path)
        content = fetch_blob_content(owner, repo, blob_sha, token)
        if content is None:
            skipped.append(path)
            file_paths.remove(path)
        else:
            files[path] = content

    return IngestResult(
        owner=owner,
        repo=repo,
        branch=resolved_branch,
        about=about,
        tree=sorted(file_paths),
        files=files,
        skipped=sorted(skipped),
    )
