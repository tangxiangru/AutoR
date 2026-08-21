"""ResearchClawBench's own judge model, so our scores need no translation.

The public leaderboard was produced by a `gpt-5.1` judge. Scoring with anything else means
carrying an offset between our numbers and theirs. This talks to gpt-5.1 directly, so a
score produced here is on the leaderboard's own scale.

Drop-in for the `structai.LLMAgent` that `evaluation/score.py` builds: same call signature,
same prompts, same rubric weights, same aggregation. Only the transport differs.

**The key is never in this file, never in a repository, and never in output.** It is read at
call time from a path outside any git tree, the file is required to be owner-only, and the
error paths report a type and a truncated message rather than echoing a request that would
carry the Authorization header.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import stat
import time
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "gpt-5.1"
DEFAULT_ENDPOINT = "https://shi-lab-2-resource.services.ai.azure.com/openai/v1"
KEY_PATH = Path(os.environ.get("RCB_JUDGE_KEY_FILE", str(Path.home() / "api.txt")))

#: score.py passes 500. gpt-5.1 spends output budget on reasoning before it answers, and at
#: 500 the answer comes back empty -- the failure that scored every Gemini-judged item zero.
DEFAULT_MAX_TOKENS = 8000
MAX_IMAGES = 15


class JudgeKeyError(RuntimeError):
    """Raised when the key cannot be read safely. Never carries the key."""


def read_api_key() -> str:
    """Load the key from disk, refusing a file other users can read."""
    if not KEY_PATH.exists():
        raise JudgeKeyError(f"No judge key at {KEY_PATH}. Write it there, owner-readable only.")
    mode = KEY_PATH.stat().st_mode
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        raise JudgeKeyError(f"{KEY_PATH} is readable by group or other. Run: chmod 600 {KEY_PATH}")
    key = KEY_PATH.read_text(encoding="utf-8").strip()
    if not key:
        raise JudgeKeyError(f"{KEY_PATH} is empty.")
    return key


def _redact(text: str, key: str) -> str:
    out = text.replace(key, "<redacted>") if key else text
    return re.sub(r"(?i)(api[-_ ]?key|authorization|bearer)\s*[:=]\s*\S+", r"\1=<redacted>", out)


def _extract_json(raw: str) -> dict[str, Any] | None:
    candidate = (raw or "").strip()
    if not candidate:
        return None
    for text in (
        candidate,
        *(m.group(1) for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)),
        *(m.group(1) for m in re.finditer(r"(\{.*\})", candidate, re.DOTALL)),
    ):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _image_part(path: str) -> dict[str, Any] | None:
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError:
        return None
    media = mimetypes.guess_type(p.name)[0] or "image/png"
    if media not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
        media = "image/png"
    encoded = base64.standard_b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{media};base64,{encoded}"}}


class Gpt51Judge:
    """Mimics the slice of ``structai.LLMAgent`` that score.py actually uses."""

    def __init__(self, api_key: str | None = None, api_base: str | None = None,
                 model_version: str = DEFAULT_MODEL, system_prompt: str = "You are a helpful assistant.",
                 temperature: float = 0, max_tokens: int | None = None, time_limit: int = 300,
                 max_try: int = 2, **_ignored: Any) -> None:
        from openai import OpenAI

        self._key = read_api_key()
        self.model = model_version if model_version and "gpt" in model_version else DEFAULT_MODEL
        self.system_prompt = system_prompt
        # Treated as a floor, never a ceiling: honouring 500 returns an empty answer.
        self.max_tokens = max(int(max_tokens or 0), DEFAULT_MAX_TOKENS)
        self.max_try = max_try
        self.client = OpenAI(
            base_url=os.environ.get("RCB_JUDGE_ENDPOINT", DEFAULT_ENDPOINT),
            api_key=self._key, timeout=float(max(time_limit, 900)), max_retries=3,
        )

    def __call__(self, query: str, *args: Any, **kwargs: Any) -> Any:
        return self.safe_api(query, *args, **kwargs)

    def safe_api(self, query: str, system_prompt: str | None = None, return_example: Any = None,
                 max_try: int | None = None, image_paths: list[str] | None = None,
                 **_ignored: Any) -> Any:
        content: list[dict[str, Any]] = [{"type": "text", "text": query}]
        for path in (image_paths or [])[:MAX_IMAGES]:
            part = _image_part(path)
            if part:
                content.append(part)
        messages = [{"role": "system", "content": system_prompt or self.system_prompt},
                    {"role": "user", "content": content}]
        attempts = max_try or self.max_try
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                reply = self.client.chat.completions.create(
                    model=self.model, messages=messages, max_completion_tokens=self.max_tokens)
                raw = (reply.choices[0].message.content or "").strip()
                if return_example is None:
                    return raw
                payload = _extract_json(raw)
                if payload is not None:
                    return payload
            except Exception as exc:  # noqa: BLE001 - retry transient transport failures
                last = exc
                time.sleep(2 + 3 * attempt)
        if last is not None:
            print(f"[gpt51_judge] failed after {attempts}: "
                  f"{type(last).__name__}: {_redact(str(last), self._key)[:200]}")
        return None
