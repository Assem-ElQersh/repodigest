"""FastAPI web server for github_ingest."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from .analyzer import PRESET_PROMPTS, PROVIDERS
from .core import DEFAULT_MAX_FILE_SIZE, ingest
from .formatter import to_dict, to_txt

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="GitHub Ingest API",
    description=(
        "Fetch a GitHub repository's metadata, directory tree, and file contents "
        "in one shot — perfect for feeding into LLMs."
    ),
    version="1.0.0",
)

# Serve the web UI static files
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    repo: str
    token: Optional[str] = None
    branch: Optional[str] = None
    max_file_size: int = DEFAULT_MAX_FILE_SIZE

    @field_validator("repo")
    @classmethod
    def repo_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("repo must not be empty")
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "repo": "owner/repo",
                    "token": "ghp_xxxxxxxxxxxx",
                    "branch": "main",
                }
            ]
        }
    }


class HealthResponse(BaseModel):
    status: str
    version: str


class AnalyzeRequest(BaseModel):
    digest: str
    api_key: str
    provider: str = "groq"
    prompt_type: str = "summary"
    custom_prompt: Optional[str] = None
    model: Optional[str] = None  # defaults to provider's first model

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "digest": "<paste your .txt digest here>",
                    "api_key": "gsk_...",
                    "provider": "groq",
                    "prompt_type": "summary",
                    "model": "llama-3.3-70b-versatile",
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    """Serve the web UI."""
    return FileResponse(str(_STATIC_DIR / "index.html"))


@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    """Liveness check."""
    return HealthResponse(status="ok", version=app.version)


@app.post("/ingest", tags=["ingest"])
async def ingest_repo(body: IngestRequest) -> dict:
    """
    Ingest a GitHub repository.

    Returns structured JSON with about metadata, directory tree, and all
    text file contents.
    """
    # Allow a server-level default token via env var
    token = body.token or os.environ.get("GITHUB_TOKEN")

    try:
        result = ingest(
            body.repo,
            token=token,
            branch=body.branch,
            max_file_size=body.max_file_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return to_dict(result)


@app.post("/ingest/txt", response_class=PlainTextResponse, tags=["ingest"])
async def ingest_repo_txt(body: IngestRequest) -> str:
    """
    Ingest a GitHub repository and return the LLM-ready plain-text digest.
    """
    token = body.token or os.environ.get("GITHUB_TOKEN")

    try:
        result = ingest(
            body.repo,
            token=token,
            branch=body.branch,
            max_file_size=body.max_file_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return to_txt(result)


@app.get("/ingest", tags=["ingest"])
async def ingest_repo_get(
    repo: str = Query(..., description="Repository as 'owner/repo' or full GitHub URL"),
    token: Optional[str] = Query(None, description="GitHub personal access token"),
    branch: Optional[str] = Query(None, description="Branch name (default: repo default)"),
    max_file_size: int = Query(DEFAULT_MAX_FILE_SIZE, description="Max file size in bytes"),
    fmt: str = Query("json", description="Output format: 'json' or 'txt'"),
) -> object:
    """
    Ingest a GitHub repository via GET query parameters.

    Use ``fmt=txt`` for the plain-text digest or ``fmt=json`` for structured JSON.
    """
    resolved_token = token or os.environ.get("GITHUB_TOKEN")

    try:
        result = ingest(
            repo,
            token=resolved_token,
            branch=branch,
            max_file_size=max_file_size,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if fmt == "txt":
        return PlainTextResponse(to_txt(result))
    return to_dict(result)


# ---------------------------------------------------------------------------
# LLM Analysis
# ---------------------------------------------------------------------------

@app.post("/analyze/test", tags=["analyze"])
async def test_api_key(body: dict) -> dict:
    """
    Send a minimal request to verify an API key and provider work.
    Expects ``{ "api_key": "...", "provider": "...", "model": "..." }``.
    """
    from .analyzer import test_key

    api_key  = body.get("api_key", "").strip()
    provider = body.get("provider", "groq")
    model    = body.get("model") or None

    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")

    try:
        reply = test_key(api_key, provider, model)
        return {"status": "ok", "provider": provider, "response": reply}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/analyze/providers", tags=["analyze"])
async def list_providers() -> dict:
    """Return all supported LLM providers, their models, and preset prompt types."""
    return {
        "providers": {
            pid: {
                "name": cfg["name"],
                "key_hint": cfg["key_hint"],
                "key_url": cfg["key_url"],
                "max_context_tokens": cfg["max_context_tokens"],
                "models": [{"id": m[0], "label": m[1]} for m in cfg["models"]],
            }
            for pid, cfg in PROVIDERS.items()
        },
        "prompt_types": list(PRESET_PROMPTS.keys()) + ["custom"],
    }


@app.post("/analyze", tags=["analyze"])
async def analyze_repo(body: AnalyzeRequest) -> StreamingResponse:
    """
    Send a repository digest to Gemini for LLM analysis.

    Returns a Server-Sent Events stream of text chunks.
    Each event is ``data: {"text": "..."}\\n\\n``.
    The final event is ``data: [DONE]\\n\\n``.
    """
    from .analyzer import analyze_stream

    def event_stream():
        try:
            for chunk in analyze_stream(
                digest=body.digest,
                api_key=body.api_key,
                provider=body.provider,
                prompt_type=body.prompt_type,
                custom_prompt=body.custom_prompt,
                model_name=body.model,
            ):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------

def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Start the uvicorn server programmatically."""
    import uvicorn
    uvicorn.run(
        "github_ingest.server:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    serve(reload=True)
