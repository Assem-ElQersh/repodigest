"""Command-line interface for github_ingest."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .core import DEFAULT_MAX_FILE_SIZE, ingest
from .formatter import to_json, to_txt


def _progress_bar(current: int, total: int, path: str) -> None:
    """Print a compact progress indicator to stderr."""
    width = 30
    filled = int(width * current / total) if total else width
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * current / total) if total else 100
    # Truncate long paths
    display_path = path if len(path) <= 45 else "…" + path[-44:]
    print(
        f"\r  [{bar}] {pct:3d}%  {current}/{total}  {display_path:<46}",
        end="",
        flush=True,
        file=sys.stderr,
    )
    if current == total:
        print(file=sys.stderr)  # newline when done


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repodigest",
        description=(
            "Fetch an entire GitHub repository — metadata, file tree, and all "
            "text file contents — and save an LLM-ready .txt digest and a "
            "structured .json file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  github-ingest owner/repo
  github-ingest https://github.com/owner/repo --token ghp_xxx
  github-ingest owner/repo --branch dev --output ./digests
  github-ingest owner/repo --max-file-size 102400 --no-json
        """,
    )
    parser.add_argument(
        "repo",
        help="Repository as 'owner/repo' or a full GitHub URL.",
    )
    parser.add_argument(
        "--token", "-t",
        default=os.environ.get("GITHUB_TOKEN"),
        metavar="TOKEN",
        help=(
            "GitHub personal access token. Raises rate limit from 60 to "
            "5,000 req/h. Defaults to $GITHUB_TOKEN env var."
        ),
    )
    parser.add_argument(
        "--branch", "-b",
        default=None,
        metavar="BRANCH",
        help="Branch to ingest (default: repo's default branch).",
    )
    parser.add_argument(
        "--output", "-o",
        default=".",
        metavar="DIR",
        help="Output directory for .txt and .json files (default: current dir).",
    )
    parser.add_argument(
        "--max-file-size",
        type=int,
        default=DEFAULT_MAX_FILE_SIZE,
        metavar="BYTES",
        help=(
            f"Maximum file size in bytes to include (default: {DEFAULT_MAX_FILE_SIZE:,}). "
            "Use 0 for no limit."
        ),
    )
    parser.add_argument(
        "--no-txt",
        action="store_true",
        help="Skip writing the .txt digest.",
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Skip writing the .json file.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Also print the .txt digest to stdout.",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    progress_fn = None if args.quiet else _progress_bar

    if not args.quiet:
        print(f"  Fetching  {args.repo} …", file=sys.stderr)

    t0 = time.monotonic()

    try:
        result = ingest(
            args.repo,
            token=args.token,
            branch=args.branch,
            max_file_size=args.max_file_size,
            on_progress=progress_fn,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\n  Error: {exc}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - t0
    slug = f"{result.owner}_{result.repo}"

    # --- Write .txt ---
    txt_content = to_txt(result)
    if not args.no_txt:
        txt_path = output_dir / f"{slug}.txt"
        txt_path.write_text(txt_content, encoding="utf-8")
        if not args.quiet:
            print(f"  Saved TXT  → {txt_path}", file=sys.stderr)

    # --- Write .json ---
    if not args.no_json:
        json_path = output_dir / f"{slug}.json"
        json_path.write_text(to_json(result), encoding="utf-8")
        if not args.quiet:
            print(f"  Saved JSON → {json_path}", file=sys.stderr)

    # --- Stats ---
    if not args.quiet:
        kb = len(txt_content.encode()) / 1024
        print(
            f"\n  Done in {elapsed:.1f}s  |  "
            f"{len(result.files):,} files ingested  |  "
            f"{len(result.skipped):,} skipped  |  "
            f"{kb:,.0f} KB total",
            file=sys.stderr,
        )

    # --- Optional stdout dump ---
    if args.stdout:
        print(txt_content)

    return 0


if __name__ == "__main__":
    sys.exit(main())
