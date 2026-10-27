"""Prompt templates live as Markdown files in this folder, one per job.

Placeholders use ``{{name}}`` so SQL braces and JSON never collide with formatting.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent


@lru_cache
def load(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **values: object) -> str:
    text = load(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", "" if value is None else str(value))
    return text
