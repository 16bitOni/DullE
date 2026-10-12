"""Personal knowledge base — retrieval-augmented context for the agent.

The user fills knowledge.yaml with facts about their setup:
  - "I have YouTube Premium" → agent won't look for skip-ad buttons
  - "Chrome Profile 2 is my work profile" → agent picks the right profile
  - "Mom's WhatsApp name is Mamoni" → agent knows who to message

At planning and execution time, relevant entries are retrieved by matching
the task text against each entry's tags and keywords.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


@dataclass
class KnowledgeEntry:
    """A single fact from the knowledge base."""
    fact: str
    tags: list[str]
    context: str = ""
    app: str = ""

    def matches(self, query_tokens: set[str]) -> int:
        """Score how relevant this entry is to a query. Higher = better match."""
        score = 0
        searchable = " ".join(self.tags).lower()
        if self.app:
            searchable += " " + self.app.lower()
        if self.context:
            searchable += " " + self.context.lower()

        for token in query_tokens:
            if token in searchable:
                score += 2
            if token in self.fact.lower():
                score += 1
        return score


class KnowledgeBase:
    """Loads and queries the user's personal knowledge file."""

    def __init__(self, path: str = "knowledge.yaml"):
        self.path = Path(path)
        self.entries: list[KnowledgeEntry] = []
        self._load()

    def _load(self):
        if not self.path.exists():
            logger.debug(f"No knowledge file at {self.path}")
            return

        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Failed to load {self.path}: {exc}")
            return

        if not isinstance(raw, list):
            logger.warning(f"knowledge.yaml should be a YAML list, got {type(raw)}")
            return

        for item in raw:
            if isinstance(item, dict) and "fact" in item:
                self.entries.append(KnowledgeEntry(
                    fact=item["fact"],
                    tags=item.get("tags", []),
                    context=item.get("context", ""),
                    app=item.get("app", ""),
                ))

        logger.info(f"Loaded {len(self.entries)} knowledge entries from {self.path}")

    def retrieve(self, task_text: str, top_k: int = 10) -> list[KnowledgeEntry]:
        """Find entries relevant to the given task text.

        Uses keyword/tag matching — fast, no embeddings needed.
        Returns up to top_k entries sorted by relevance score.
        """
        if not self.entries:
            return []

        tokens = _tokenize(task_text)
        scored = []
        for entry in self.entries:
            score = entry.matches(tokens)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    def retrieve_for_app(self, app_name: str) -> list[KnowledgeEntry]:
        """Find all entries tagged for a specific app."""
        if not self.entries:
            return []
        app_lower = app_name.lower()
        return [e for e in self.entries if e.app.lower() == app_lower
                or app_lower in [t.lower() for t in e.tags]]

    def format_for_prompt(self, entries: list[KnowledgeEntry]) -> str:
        """Format retrieved entries as a text block for injection into prompts."""
        if not entries:
            return ""
        lines = ["USER KNOWLEDGE (personal preferences and setup — use these facts):"]
        for e in entries:
            line = f"  - {e.fact}"
            if e.context:
                line += f" ({e.context})"
            lines.append(line)
        return "\n".join(lines)


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase keyword tokens for matching."""
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    words = text.split()
    # Filter out very common words that don't help matching
    stop = {"the", "a", "an", "and", "or", "to", "in", "on", "for", "is", "it",
            "my", "me", "i", "do", "can", "will", "that", "this", "with", "from"}
    return {w for w in words if w not in stop and len(w) > 1}
