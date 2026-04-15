# repodigest

Fetch any GitHub repository via the GitHub API and produce an **LLM-ready text digest** and a **structured JSON file** — including the repo's "about" metadata, full directory tree, and all file contents. Then optionally pass the digest directly to an LLM for deep analysis.

---

## Features

- Repo "about" metadata: description, homepage, topics, stars, forks, watchers, license, language
- Full recursive directory tree rendered as ASCII art
- All text file contents concatenated with clear separators
- Automatic filtering of binary files and noise directories
- Configurable max file size (100 KB → No limit)
- **Web UI** with live progress bar, results tabs, and download buttons
- **LLM Analysis panel** — send the digest to Groq, Mistral, OpenRouter, or Gemini with 5 preset prompts
- **CLI**, **importable Python library**, and **FastAPI server**
- GitHub token support (raises rate limit from 60 to 5,000 req/h)
- Outputs both `.txt` (LLM digest) and `.json` (structured data)

---

## Installation

```bash
pip install -r requirements.txt
```

---

## Quick Start

```bash
# Start the web UI
uvicorn github_ingest.server:app --reload --port 8001

# Open in browser
http://localhost:8001
```

---

## Web UI

Visit **[http://localhost:8001](http://localhost:8001)** after starting the server.

### Repo Fetch panel
- Enter any `owner/repo` or full GitHub URL
- Optional: GitHub token, branch, max file size (including **No limit**)
- Live progress bar while ingesting
- Results: about card (description, topics, stats), summary, directory tree
- Switch between **TXT digest / JSON / File tree** tabs
- Copy to clipboard or download `.txt` / `.json`

### LLM Analysis panel (below results)
- Select a provider, paste your API key, pick a model
- Choose an analysis type or write a custom prompt
- Response streams live into the browser
- Copy the analysis to clipboard

---

## LLM Providers

All providers below offer a **free tier with no credit card required** (except Gemini in some regions).

| Provider | Free? | Context | Sign-up |
|---|---|---|---|
| **Groq** ⭐ recommended | Free, no card | 128k tokens | [console.groq.com](https://console.groq.com) |
| **Mistral** | Free, no card | 32k tokens | [console.mistral.ai](https://console.mistral.ai) |
| **OpenRouter** | Free models, no card | up to 131k | [openrouter.ai/keys](https://openrouter.ai/keys) |
| Gemini | Free (may need billing) | 1M tokens | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |

### Analysis presets

| Preset | What it covers |
|---|---|
| **Summary** | Purpose, architecture, key modules, dependencies, entry points |
| **Architecture** | Design patterns, module interactions, data flow, coupling |
| **Security Review** | Vulnerabilities, input validation, secrets, findings by severity |
| **Onboarding Guide** | Setup, structure tour, how to run, common tasks, gotchas |
| **Code Quality** | Score 1–10, organisation, docs, tests, duplication, top improvements |
| **Custom** | Write your own prompt |

---

## CLI Usage

```bash
# Basic — writes owner_repo.txt and owner_repo.json in current directory
python -m github_ingest owner/repo

# Full GitHub URL works too
python -m github_ingest https://github.com/owner/repo

# Authenticate (recommended — raises rate limit from 60 to 5,000 req/h)
python -m github_ingest owner/repo --token ghp_xxxxxxxxxxxx

# Or use an environment variable
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
python -m github_ingest owner/repo

# Specific branch
python -m github_ingest owner/repo --branch dev

# Custom output directory
python -m github_ingest owner/repo --output ./digests

# Limit file size (skip files larger than 100 KB)
python -m github_ingest owner/repo --max-file-size 102400

# No file size limit
python -m github_ingest owner/repo --max-file-size 0

# Only produce the JSON file
python -m github_ingest owner/repo --no-txt

# Print the text digest to stdout
python -m github_ingest owner/repo --stdout

# Suppress all progress output
python -m github_ingest owner/repo --quiet
```

Output files are named `{owner}_{repo}.txt` and `{owner}_{repo}.json`.

---

## Python Library Usage

```python
from github_ingest import ingest, to_txt, to_json, to_dict

# Fetch the repo
result = ingest("owner/repo", token="ghp_xxx")

# Access structured data
print(result.about["description"])
print(result.about["topics"])
print(result.about["stars"])
print(result.tree)                     # ["README.md", "src/main.py", ...]
print(result.files["README.md"])       # raw file content

# Render outputs
txt_digest  = to_txt(result)           # LLM-ready plain text
json_string = to_json(result)          # pretty-printed JSON string
data_dict   = to_dict(result)          # plain Python dict

# No file size limit
result = ingest("owner/repo", max_file_size=0)
```

### LLM analysis from Python

```python
from github_ingest import ingest, to_txt
from github_ingest.analyzer import analyze_stream

result = ingest("owner/repo", token="ghp_xxx")
digest = to_txt(result)

# Stream analysis using Groq (free, no card)
for chunk in analyze_stream(
    digest=digest,
    api_key="gsk_...",
    provider="groq",
    prompt_type="summary",
    model_name="llama-3.3-70b-versatile",
):
    print(chunk, end="", flush=True)
```

### Individual fetchers

```python
from github_ingest import fetch_repo_about, fetch_repo_tree, fetch_blob_content

about   = fetch_repo_about("owner", "repo", token="ghp_xxx")
blobs   = fetch_repo_tree("owner", "repo", sha="<commit-sha>", token="ghp_xxx")
content = fetch_blob_content("owner", "repo", blob_sha="<sha>", token="ghp_xxx")
```

---

## FastAPI Server

### Start

```bash
uvicorn github_ingest.server:app --reload --port 8001
```

Set `GITHUB_TOKEN` in the environment to apply a default token to all ingest requests:

```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
uvicorn github_ingest.server:app --reload --port 8001
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web UI |
| `GET` | `/health` | Liveness check |
| `POST` | `/ingest` | Ingest repo → JSON |
| `POST` | `/ingest/txt` | Ingest repo → plain-text digest |
| `GET` | `/ingest?repo=owner/repo&fmt=json` | Ingest via query params |
| `GET` | `/analyze/providers` | List providers, models, prompt types |
| `POST` | `/analyze` | Analyze digest → SSE stream |
| `POST` | `/analyze/test` | Test an API key with a minimal request |

### POST /ingest

```json
{
  "repo": "owner/repo",
  "token": "ghp_xxxxxxxxxxxx",
  "branch": "main",
  "max_file_size": 524288
}
```

Set `max_file_size` to `0` for no limit. `token` falls back to the `GITHUB_TOKEN` env var.

### POST /analyze

```json
{
  "digest": "<your .txt digest>",
  "api_key": "gsk_...",
  "provider": "groq",
  "prompt_type": "summary",
  "model": "llama-3.3-70b-versatile"
}
```

`provider` options: `groq` · `mistral` · `openrouter` · `gemini`  
`prompt_type` options: `summary` · `architecture` · `security` · `onboarding` · `quality` · `custom`  
Returns a **Server-Sent Events** stream: `data: {"text": "..."}` chunks, ending with `data: [DONE]`.

### POST /analyze/test

```json
{ "api_key": "gsk_...", "provider": "groq", "model": "llama-3.3-70b-versatile" }
```

Sends a minimal request to verify the key works before sending the full digest.

### Interactive API docs

[http://localhost:8001/docs](http://localhost:8001/docs)

---

## Output Format

### `.txt` digest

```
================================================================
REPOSITORY: owner/repo  [main]
================================================================

ABOUT
-----
Description : A great project
Homepage    : https://example.com
Language    : Python
License     : MIT
Topics      : python, llm, tools
Stats       : Stars: 1,234 | Forks: 56 | Watchers: 89 | Open issues: 12

================================================================
SUMMARY
================================================================
Files ingested : 42
Files skipped  : 8

================================================================
DIRECTORY STRUCTURE
================================================================
repo/
├── README.md
├── src/
│   ├── main.py
│   └── utils.py
└── tests/
    └── test_main.py

================================================================
FILES
================================================================
──── README.md ────────────────────────────────────────────────
# My Project
...
```

### `.json` output

```json
{
  "repository": "owner/repo",
  "branch": "main",
  "about": {
    "description": "A great project",
    "topics": ["python", "llm"],
    "stars": 1234,
    "license": "MIT"
  },
  "summary": { "files_ingested": 42, "files_skipped": 8 },
  "tree": ["README.md", "src/main.py"],
  "files": { "README.md": "# My Project\n..." },
  "skipped": ["assets/logo.png"]
}
```

---

## GitHub Rate Limits

| | Unauthenticated | With token |
|---|---|---|
| Limit | 60 req/hour | 5,000 req/hour |
| Small repo (~20 files) | Works | Works |
| Medium repo (~200 files) | Hits limit | Works |
| Large repo (1000+ files) | Fails | Works |

Get a free token at [github.com/settings/tokens/new](https://github.com/settings/tokens/new) — no scopes needed for public repos.

---

## Filtered by Default

**Binary extensions:** images, audio, video, archives, compiled objects, fonts, office docs, databases

**Noise directories:** `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `dist`, `build`, `.next`, `.pytest_cache`, and more

**Files over 500 KB** are skipped by default. Override with `--max-file-size <bytes>` or `0` for no limit.

---

## License

MIT License. See the [LICENSE](LICENSE) file for details.
