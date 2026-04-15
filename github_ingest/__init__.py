"""
github_ingest
=============

Fetch an entire GitHub repository — about metadata, directory tree, and all
text file contents — in one call.  Output is available as a plain-text LLM
digest, structured JSON, or a Python dataclass.

Quick start
-----------
    from github_ingest import ingest

    result = ingest("owner/repo", token="ghp_xxx")

    print(result.about)          # description, topics, stars, …
    print(result.tree)           # sorted list of file paths
    print(result.files["README.md"])  # raw file content

    from github_ingest import to_txt, to_json
    txt  = to_txt(result)        # LLM-ready plain-text digest
    json = to_json(result)       # pretty-printed JSON string
"""

from .core import (
    DEFAULT_MAX_FILE_SIZE,
    IngestResult,
    fetch_blob_content,
    fetch_repo_about,
    fetch_repo_tree,
    fetch_user_repos,
    ingest,
)
from .formatter import to_dict, to_json, to_txt

__all__ = [
    # Core
    "ingest",
    "IngestResult",
    "fetch_repo_about",
    "fetch_repo_tree",
    "fetch_blob_content",
    "fetch_user_repos",
    "DEFAULT_MAX_FILE_SIZE",
    # Formatters
    "to_txt",
    "to_json",
    "to_dict",
]

__version__ = "1.0.0"
