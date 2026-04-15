"""Multi-provider LLM analysis of ingested repository digests."""

from __future__ import annotations

import re
from typing import Iterator, Optional

# ---------------------------------------------------------------------------
# Provider catalogue
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, dict] = {
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "key_url": "console.groq.com",
        "key_hint": "Free at console.groq.com — no credit card",
        "models": [
            ("llama-3.3-70b-versatile",  "Llama 3.3 70B · 128k ctx · recommended"),
            ("llama-3.1-70b-versatile",  "Llama 3.1 70B · 128k ctx"),
            ("llama-3.1-8b-instant",     "Llama 3.1 8B · 128k ctx · fastest"),
            ("mixtral-8x7b-32768",       "Mixtral 8x7B · 32k ctx"),
            ("gemma2-9b-it",             "Gemma 2 9B · 8k ctx"),
        ],
        "max_context_tokens": 128_000,
        "protocol": "openai",
    },
    "mistral": {
        "name": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "key_url": "console.mistral.ai",
        "key_hint": "Free tier at console.mistral.ai — no credit card",
        "models": [
            ("mistral-small-latest",  "Mistral Small · 32k ctx"),
            ("open-mistral-7b",       "Mistral 7B (open) · 32k ctx"),
            ("mistral-large-latest",  "Mistral Large · 128k ctx"),
        ],
        "max_context_tokens": 32_000,
        "protocol": "openai",
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_url": "openrouter.ai/keys",
        "key_hint": "Free models at openrouter.ai — no credit card",
        "models": [
            ("meta-llama/llama-3.1-8b-instruct:free",  "Llama 3.1 8B · 131k ctx · free"),
            ("meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 70B · 131k ctx · free"),
            ("google/gemma-3-27b-it:free",             "Gemma 3 27B · 96k ctx · free"),
            ("mistralai/mistral-7b-instruct:free",     "Mistral 7B · 32k ctx · free"),
        ],
        "max_context_tokens": 131_000,
        "protocol": "openai",
    },
    "gemini": {
        "name": "Google Gemini",
        "base_url": None,
        "key_url": "aistudio.google.com/apikey",
        "key_hint": "Free at aistudio.google.com — may require billing in some regions",
        "models": [
            ("gemini-2.0-flash",               "Gemini 2.0 Flash · 1M ctx"),
            ("gemini-2.0-flash-thinking-exp",  "Gemini 2.0 Flash Thinking · 1M ctx"),
            ("gemini-1.5-pro",                 "Gemini 1.5 Pro · 2M ctx"),
            ("gemini-1.5-flash",               "Gemini 1.5 Flash · 1M ctx"),
        ],
        "max_context_tokens": 1_000_000,
        "protocol": "gemini",
    },
}

# ---------------------------------------------------------------------------
# Preset prompts
# ---------------------------------------------------------------------------

PRESET_PROMPTS: dict[str, str] = {
    "summary": """\
Analyze this repository digest and provide a thorough summary covering:

1. **Purpose & Goals** — What does this project do and why does it exist?
2. **Architecture** — How is the codebase structured? What patterns are used?
3. **Key Modules** — The most important files/modules and what each does.
4. **Dependencies** — Main external dependencies and why they are needed.
5. **Entry Points** — How is the project started or consumed?
6. **Notable Patterns** — Interesting design decisions worth calling out.

Be specific and reference actual file names and code where relevant.""",

    "architecture": """\
Perform a deep architecture review of this repository:

1. **High-level Design** — Overall architectural pattern (MVC, microservices, layered, etc.)
2. **Module Interactions** — How do the components interact with each other?
3. **Data Flow** — How does data move through the system end-to-end?
4. **Abstractions** — Key interfaces, base classes, or protocols defined.
5. **Design Patterns** — Specific patterns used (factory, observer, strategy, etc.)
6. **Scalability** — How well does the architecture scale? Any bottlenecks?
7. **Coupling & Cohesion** — Assessment of module boundaries and separation of concerns.

Reference specific files and code snippets to support every claim.""",

    "security": """\
Perform a security review of this repository:

1. **Authentication & Authorization** — How is access control handled?
2. **Input Validation** — Is user input properly validated and sanitized?
3. **Secrets Management** — Are credentials/keys handled safely (no hardcoding)?
4. **Dependencies** — Any known-vulnerable or outdated dependencies?
5. **Common Vulnerabilities** — Check for injection, XSS, CSRF, path traversal, SSRF, etc.
6. **Error Handling** — Does error output leak sensitive information?
7. **Risk Summary** — List all findings by severity: Critical / High / Medium / Low / Info.

Be specific about file locations and code context for every finding.""",

    "onboarding": """\
Write a comprehensive onboarding guide for a developer new to this project:

1. **Project Overview** — What it is and why it exists.
2. **Prerequisites** — Tools, runtimes, and accounts needed.
3. **Setup Steps** — Exact step-by-step instructions to get it running locally.
4. **Project Structure** — A guided tour of the key directories and files.
5. **How to Run** — Start the app, run tests, build for production.
6. **Key Concepts** — Domain or architectural concepts a newcomer must understand.
7. **Common Tasks** — How to do the most frequent day-to-day development tasks.
8. **Gotchas** — Non-obvious things that will trip someone up.

Write this as if explaining to a competent developer who is brand new to this codebase.""",

    "quality": """\
Assess the code quality of this repository:

1. **Overall Score** — Rate 1–10 with a one-line justification.
2. **Code Organisation** — Is the structure logical and consistent?
3. **Documentation** — Quality of comments, docstrings, and README.
4. **Test Coverage** — Are there tests? Are they meaningful and comprehensive?
5. **Error Handling** — Is error handling robust and consistent throughout?
6. **Code Duplication** — Notable DRY violations or copy-paste patterns?
7. **Complexity** — Overly complex functions, classes, or modules?
8. **Best Practices** — Language/framework idioms and conventions followed?
9. **Top 5 Improvements** — Prioritised, actionable list of what to fix first.

Be constructive and give specific file/function references for every point.""",
}


# ---------------------------------------------------------------------------
# Core streaming function
# ---------------------------------------------------------------------------

def analyze_stream(
    digest: str,
    api_key: str,
    provider: str = "groq",
    prompt_type: str = "summary",
    custom_prompt: Optional[str] = None,
    model_name: Optional[str] = None,
) -> Iterator[str]:
    """
    Stream an LLM analysis of a repository digest.

    Yields text chunks as they arrive from the model.
    Raises ``RuntimeError`` with a clean human-readable message on failure.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider '{provider}'. Choose from: {list(PROVIDERS)}")

    cfg = PROVIDERS[provider]

    # Resolve model
    if not model_name:
        model_name = cfg["models"][0][0]

    # Resolve prompt
    if prompt_type == "custom":
        if not custom_prompt or not custom_prompt.strip():
            raise ValueError("A custom prompt is required when prompt_type is 'custom'.")
        system_prompt = custom_prompt.strip()
    else:
        system_prompt = PRESET_PROMPTS.get(prompt_type, PRESET_PROMPTS["summary"])

    full_prompt = (
        f"{system_prompt}\n\n"
        f"{'─' * 64}\n\n"
        f"REPOSITORY DIGEST:\n\n{digest}"
    )

    try:
        if cfg["protocol"] == "openai":
            yield from _stream_openai(full_prompt, api_key, cfg["base_url"], model_name)
        else:
            yield from _stream_gemini(full_prompt, api_key, model_name)
    except RuntimeError:
        raise
    except Exception as exc:
        raise _clean_error(exc, provider) from exc


# ---------------------------------------------------------------------------
# Protocol implementations
# ---------------------------------------------------------------------------

def _stream_openai(prompt: str, api_key: str, base_url: str, model: str) -> Iterator[str]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package not installed. Run: pip install openai") from exc

    client = OpenAI(api_key=api_key, base_url=base_url)
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    for chunk in stream:
        text = chunk.choices[0].delta.content
        if text:
            yield text


def _stream_gemini(prompt: str, api_key: str, model: str) -> Iterator[str]:
    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise RuntimeError(
            "google-generativeai not installed. Run: pip install google-generativeai"
        ) from exc

    genai.configure(api_key=api_key)
    mdl = genai.GenerativeModel(model)
    response = mdl.generate_content(prompt, stream=True)
    for chunk in response:
        text = getattr(chunk, "text", None)
        if text:
            yield text


# ---------------------------------------------------------------------------
# Error cleaning
# ---------------------------------------------------------------------------

def _clean_error(exc: Exception, provider: str = "") -> RuntimeError:
    msg = str(exc)
    cfg = PROVIDERS.get(provider, {})
    key_url = cfg.get("key_url", "the provider's website")

    # Invalid / missing key
    if any(x in msg for x in ("401", "403", "API_KEY_INVALID", "Unauthorized", "Authentication")):
        return RuntimeError(
            f"Invalid or missing API key. Get a free key at {key_url}."
        )

    # Rate limit / quota
    if "429" in msg or "quota" in msg.lower() or "rate_limit" in msg.lower() or "rate limit" in msg.lower():
        delay_match = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", msg)
        delay = f" Retry in {delay_match.group(1)}s." if delay_match else ""

        if "limit: 0" in msg:
            return RuntimeError(
                f"Quota is set to zero for this key. Make sure you created the key at "
                f"{key_url} and that the free tier is enabled for your account."
            )
        if "PerDay" in msg or "per_day" in msg.lower():
            return RuntimeError(
                f"Daily quota exhausted.{delay} Resets at midnight. "
                f"Consider switching to a different provider."
            )
        retry_secs = int(delay_match.group(1)) if delay_match else 999
        if retry_secs <= 120:
            return RuntimeError(f"Per-minute rate limit hit.{delay} Wait a moment and retry.")

        return RuntimeError(f"API quota exceeded.{delay}")

    # Context too long
    if "context" in msg.lower() and ("too long" in msg.lower() or "exceed" in msg.lower()):
        return RuntimeError(
            "The digest exceeds this model's context window. "
            "Try a smaller repo, lower the Max file size, or switch to a model with a larger context."
        )

    # Model not found
    if "404" in msg or "model" in msg.lower() and "not found" in msg.lower():
        return RuntimeError(
            f"Model not found or not available on your plan. "
            f"Try a different model from the dropdown."
        )

    # Generic — first line only, no proto dump
    first_line = msg.splitlines()[0][:200]
    return RuntimeError(first_line)


# ---------------------------------------------------------------------------
# Test helper
# ---------------------------------------------------------------------------

def test_key(api_key: str, provider: str, model_name: Optional[str] = None) -> str:
    """Send a minimal request and return the model's response text."""
    cfg = PROVIDERS[provider]
    if not model_name:
        model_name = cfg["models"][0][0]

    chunks = list(analyze_stream(
        digest="",
        api_key=api_key,
        provider=provider,
        prompt_type="custom",
        custom_prompt='Reply with exactly: "OK"',
        model_name=model_name,
    ))
    return "".join(chunks).strip()
