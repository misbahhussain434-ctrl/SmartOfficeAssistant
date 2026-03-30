from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional


def _fallback_summarize(text: str, max_sentences: int = 3, max_chars: int = 450) -> str:
    """Cheap summary that works without ML models."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""

    # Split on common sentence enders.
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    summary = " ".join(parts[:max_sentences]).strip()
    summary = summary[:max_chars].strip()
    if not summary:
        summary = cleaned[:max_chars].strip()
    return summary


@lru_cache(maxsize=2)
def get_summarization_pipeline(model_name: str):
    """
    Build and cache a Hugging Face summarization pipeline (CPU).
    """
    from transformers import pipeline

    # device=-1 forces CPU
    return pipeline("summarization", model=model_name, device=-1)


def summarize_text(
    text: str,
    model_name: str = "sshleifer/distilbart-cnn-12-6",
    max_new_tokens: int = 160,
    min_new_tokens: int = 30,
) -> str:
    """
    Summarize an input text.

    Falls back to a heuristic summary if the model fails to load/run.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    # Cap inputs so the model doesn't get huge (prevents long waits/errors).
    # Many models perform best with relatively shorter inputs.
    if len(cleaned) > 6000:
        cleaned = cleaned[:6000]

    try:
        pipe = get_summarization_pipeline(model_name)
        result = pipe(
            cleaned,
            max_new_tokens=max_new_tokens,
            min_new_tokens=min_new_tokens,
            do_sample=False,
            truncation=True,
        )
        generated = result[0].get("summary_text", "") if result else ""
        return (generated or "").strip() or _fallback_summarize(cleaned)
    except Exception:
        # Common causes: first-time model download, missing deps, offline environment, etc.
        return _fallback_summarize(cleaned)


def format_preview(text: str, max_chars: int = 180) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def parse_tasks(task_str: str, priority_str: str) -> list[dict]:
    """
    Convert comma-separated tasks and priorities into structured tasks.

    Example:
      task_str: "Send report, Book meeting"
      priority_str: "high, medium"
    """
    tasks = [(t or "").strip() for t in (task_str or "").split(",") if (t or "").strip()]
    priorities = [(p or "").strip().lower() for p in (priority_str or "").split(",") if (p or "").strip()]

    out: list[dict] = []
    for i, t in enumerate(tasks):
        p = priorities[i] if i < len(priorities) else (priorities[-1] if priorities else "medium")
        if p not in {"low", "medium", "high"}:
            p = "medium"
        out.append({"task": t, "priority": p})
    return out

