"""Claude access with two backends.

- claude_code (default): shells out to the Claude Code CLI in headless mode, which runs under
  your Claude subscription. Structured output via --json-schema.
- api: the Anthropic SDK with an ANTHROPIC_API_KEY (pay as you go).
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from radar.config import Config

APP_DIR = os.path.expanduser("~/Library/Application Support/Claude/claude-code")
IS_MAC = sys.platform == "darwin"
TRANSIENT_RETRIES = 2


def schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema for structured outputs (strict: no extra keys, everything required)."""
    s = model.model_json_schema()
    _strictify(s)
    return s


def _strictify(s: dict[str, Any]) -> None:
    if s.get("type") == "object":
        s["additionalProperties"] = False
        s["required"] = list(s.get("properties", {}).keys())
        for v in s.get("properties", {}).values():
            _strictify(v)
    if "items" in s and isinstance(s["items"], dict):
        _strictify(s["items"])
    for v in (s.get("$defs") or {}).values():
        _strictify(v)
    s.pop("title", None)


def claude_bin(cfg: Config) -> str:
    """The Claude Code executable: RADAR_CLAUDE_BIN, settings, PATH, or the desktop app bundle."""
    for cand in [os.environ.get("RADAR_CLAUDE_BIN"), cfg.settings.claude_bin]:
        if cand and Path(os.path.expanduser(cand)).exists():
            return os.path.expanduser(cand)
    for cand in [shutil.which("claude"), os.path.expanduser("~/.local/bin/claude"), "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]:
        if cand and os.access(cand, os.X_OK):
            return cand
    # the desktop app's bundle: layout has changed between versions, so search any depth and take the newest
    bundled = [p for p in glob.glob(os.path.join(APP_DIR, "**", "claude.app", "Contents", "MacOS", "claude"), recursive=True) if os.access(p, os.X_OK)]
    if bundled:
        return max(bundled, key=os.path.getmtime)
    raise RuntimeError("Claude Code binary not found: install Claude Code (https://claude.ai/install.sh) or set RADAR_CLAUDE_BIN")


def is_auth_error(msg: str) -> bool:
    m = msg.lower()
    return "authenticate" in m or "oauth" in m or "not logged in" in m or "login" in m


def is_setup_error(msg: str) -> bool:
    return "binary not found" in msg.lower()


class LLMError(RuntimeError):
    pass


def generate(cfg: Config, *, model: str, system: str, user: str, schema: dict[str, Any],
             effort: str | None = None, max_tokens: int = 16000) -> dict[str, Any]:
    """One structured completion. Returns the parsed JSON object."""
    if cfg.settings.backend == "api":
        return _generate_api(model, system, user, schema, effort, max_tokens)
    return _generate_claude_code(cfg, model, system, user, schema, effort)


def _generate_claude_code(cfg: Config, model: str, system: str, user: str, schema: dict[str, Any], effort: str | None) -> dict[str, Any]:
    """Retry transient failures (timeouts, 5xx, rate limits); give up at once on auth or setup errors."""
    import time
    last: Exception | None = None
    for attempt in range(TRANSIENT_RETRIES + 1):
        try:
            return _generate_claude_code_once(cfg, model, system, user, schema, effort)
        except LLMError as e:
            last = e
            if is_auth_error(str(e)) or is_setup_error(str(e)):
                raise
            time.sleep(20 * (attempt + 1))
    assert last is not None
    raise last


def _generate_claude_code_once(cfg: Config, model: str, system: str, user: str, schema: dict[str, Any], effort: str | None) -> dict[str, Any]:
    cmd = [claude_bin(cfg), "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
           "--system-prompt", system, "--model", model, "--tools", "", "--no-session-persistence",
           "--setting-sources", "", "--max-turns", "3"]
    if effort:
        cmd += ["--effort", effort]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}  # allow running from inside a Claude session
    env.setdefault("DISABLE_AUTOUPDATER", "1")                      # never update mid-run
    env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")  # no telemetry, update checks, etc.
    env.setdefault("DISABLE_TELEMETRY", "1")
    token = stored_token()
    if token and "CLAUDE_CODE_OAUTH_TOKEN" not in env:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    debug = os.environ.get("RADAR_CLAUDE_DEBUG") or str(log_dir() / "claude.log")
    cmd += ["--debug-file", debug]
    try:
        out = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=cfg.settings.llm_timeout, env=env,
                             cwd=str(cfg.root))
    except subprocess.TimeoutExpired as e:
        raise LLMError(f"claude timed out after {cfg.settings.llm_timeout}s") from e
    try:
        data = json.loads(out.stdout) if out.stdout.strip().startswith("{") else {}
    except json.JSONDecodeError:
        data = {}
    if data.get("is_error") or out.returncode != 0:
        detail = data.get("result") or out.stderr.strip() or out.stdout.strip()
        raise LLMError(f"claude error (exit {out.returncode}): {str(detail)[:500]}")
    if isinstance(data.get("structured_output"), dict):
        return data["structured_output"]
    result = data.get("result") or ""
    try:
        return json.loads(result)
    except json.JSONDecodeError as e:
        raise LLMError(f"no structured output: {result[:300]}") from e


KEYCHAIN_SERVICE = "paper-radar-claude-token"


def token_file() -> Path:
    """Where bin/claude-login.sh stores the token on Linux (macOS uses the keychain)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "paper-radar" / "token"


def log_dir() -> Path:
    """~/Library/Logs on macOS, ~/.local/state/paper-radar elsewhere."""
    if IS_MAC:
        d = Path(os.path.expanduser("~/Library/Logs"))
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        d = Path(base) / "paper-radar"
    d.mkdir(parents=True, exist_ok=True)
    return d


def stored_token() -> str | None:
    """A long-lived token from `claude setup-token`, stored with bin/claude-login.sh:
    macOS keychain first, then the token file. None means Claude Code's own login is used."""
    if IS_MAC:
        try:
            out = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                                 capture_output=True, text=True, timeout=10)
            if out.stdout.strip():
                return out.stdout.strip()
        except Exception:
            pass
    try:
        return token_file().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _generate_api(model: str, system: str, user: str, schema: dict[str, Any], effort: str | None, max_tokens: int) -> dict[str, Any]:
    import anthropic

    client = anthropic.Anthropic()
    output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
    if effort:
        output_config["effort"] = effort
    msg = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": user}], output_config=output_config)
    if msg.stop_reason == "refusal":
        raise LLMError("request refused")
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return json.loads(text)


def pdf_text(data: bytes, max_chars: int = 180_000) -> str:
    """Plain text of a PDF, truncated, for the deep read."""
    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        parts = []
        total = 0
        for page in reader.pages:
            t = page.extract_text() or ""
            parts.append(t)
            total += len(t)
            if total > max_chars:
                break
        text = "\n".join(parts)
    except Exception:
        return ""
    return text[:max_chars]
