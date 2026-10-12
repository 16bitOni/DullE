"""LLM client — single OpenAI-compatible endpoint, multiple models.

One API key + one base URL. Switch models by name for each role:
  planner  → cheap text model   (e.g. deepseek-chat)
  executor → vision model       (e.g. qwen-vl-max)
  verifier → reliable model     (e.g. claude-sonnet-4-6)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from openai import OpenAI

from dulle.config import Settings

MAX_RETRIES = 3
RETRY_DELAYS = [1, 3, 8]  # seconds between retries (exponential-ish)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass
class TokenUsage:
    """Accumulated token usage across all LLM calls."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    _per_call: list[dict] = field(default_factory=list)

    def record(self, usage, role: str, model: str):
        if usage is None:
            return
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        completion = getattr(usage, "completion_tokens", 0) or 0
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self.call_count += 1
        self._per_call.append({
            "role": role, "model": model,
            "prompt_tokens": prompt, "completion_tokens": completion,
        })

    def summary(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
        }


class LLMClient:
    """Unified client — one connection, swap models per call."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
        )
        self.usage = TokenUsage()
        self._executor_escalated = False

    def _model_for(self, role: str) -> str:
        """Resolve the model name for a role."""
        s = self.settings
        if role == "planner":
            return s.planner_model
        elif role == "verifier":
            return s.verifier_model
        elif role == "executor" and self._executor_escalated and s.executor_model_heavy:
            return s.executor_model_heavy
        else:
            return s.executor_model

    def escalate_executor(self):
        """Switch executor to the heavy model for the current step."""
        if self.settings.executor_model_heavy:
            self._executor_escalated = True
            logger.info(f"Escalated executor to {self.settings.executor_model_heavy}")
            return True
        return False

    def reset_executor(self):
        """Reset executor back to the default cheap model."""
        self._executor_escalated = False

    def _call_with_retry(self, params: dict, role: str) -> Any:
        """Call the API with retry on transient errors."""
        model = params.get("model", "unknown")
        last_exc = None

        for attempt in range(MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(**params)
                self.usage.record(response.usage, role, model)
                return response
            except Exception as exc:
                last_exc = exc
                status = getattr(exc, "status_code", None)

                if status and status in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        f"LLM call failed (status={status}), "
                        f"retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    time.sleep(delay)
                    continue

                raise

        raise last_exc

    # ── Text-only call (for planner / verifier) ──────────────────

    def text_chat(
        self,
        role: str,
        system: str,
        user_message: str,
        temperature: float = 0.3,
    ) -> str:
        """Send a text-only message, return the text response."""
        model = self._model_for(role)
        response = self._call_with_retry({
            "model": model,
            "temperature": temperature,
            "max_tokens": self.settings.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        }, role)
        return response.choices[0].message.content or ""

    # ── Single-shot vision call ──────────────────────────────────

    def vision_chat(
        self,
        system: str,
        user_text: str,
        image_b64: str,
        media_type: str = "image/png",
        temperature: float = 0.2,
        json_mode: bool = True,
        role: str = "executor",
    ) -> str:
        """Send text + screenshot to a vision model, return text response."""
        model = self._model_for(role)

        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {
                "url": f"data:{media_type};base64,{image_b64}",
            }},
        ]

        params: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": self.settings.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        }
        if json_mode:
            params["response_format"] = {"type": "json_object"}

        response = self._call_with_retry(params, role)
        return response.choices[0].message.content or ""

    # ── Multi-turn vision call (executor with memory) ────────────

    def vision_chat_multi(
        self,
        system: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        json_mode: bool = True,
        role: str = "executor",
    ) -> str:
        """Send a full multi-turn conversation with images.

        `messages` is a list of {"role": ..., "content": ...} dicts.
        The model sees the entire conversation so it knows what it
        already tried.
        """
        model = self._model_for(role)

        full_messages = [{"role": "system", "content": system}] + messages

        params: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": self.settings.max_tokens,
            "messages": full_messages,
        }
        if json_mode:
            params["response_format"] = {"type": "json_object"}

        response = self._call_with_retry(params, role)
        return response.choices[0].message.content or ""


def parse_json_response(text: str) -> dict:
    """Extract a JSON object from LLM output, tolerating markdown fences."""
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    return {"error": "Failed to parse JSON", "raw": text[:500]}
