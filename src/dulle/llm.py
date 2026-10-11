"""LLM client — single OpenAI-compatible endpoint, multiple models.

One API key + one base URL. Switch models by name for each role:
  planner  → cheap text model   (e.g. deepseek-chat)
  executor → vision model       (e.g. qwen-vl-max)
  verifier → reliable model     (e.g. claude-sonnet-4-6)
"""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from dulle.config import Settings


class LLMClient:
    """Unified client — one connection, swap models per call."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
        )

    def _model_for(self, role: str) -> str:
        """Resolve the model name for a role."""
        s = self.settings
        if role == "planner":
            return s.planner_model
        elif role == "verifier":
            return s.verifier_model
        else:
            return s.executor_model

    # ── Text-only call (for planner / verifier) ──────────────────

    def text_chat(
        self,
        role: str,  # "planner" | "verifier" | "executor"
        system: str,
        user_message: str,
        temperature: float = 0.3,
    ) -> str:
        """Send a text-only message, return the text response."""
        model = self._model_for(role)
        response = self._client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=self.settings.max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        )
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

        response = self._client.chat.completions.create(**params)
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

        response = self._client.chat.completions.create(**params)
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
