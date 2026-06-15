"""Analyzer backends for the universal pipeline runner.

Two backends share one call shape ``analyzer(prompt, model) -> str`` returning a
clean JSON string the runner parses for ``{"segments": [...]}``:

- :func:`call_claude_p` shells out to ``claude -p`` (already authenticated in this
  environment) and strips the ```json fences ``claude -p`` wraps responses in.
- :func:`mock_analyzer` returns a deterministic single-segment-per-chunk payload
  for offline tests — no network.

:func:`get_analyzer` dispatches by name.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Callable

MODEL_MAP = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
}

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)


def strip_json_fence(text: str) -> str:
    """Remove a surrounding ```json ... ``` (or bare ```) fence if present."""
    match = _FENCE_RE.match(text.strip())
    if match:
        return match.group(1).strip()
    return text.strip()


def resolve_model(model: str) -> str:
    """Map a short alias (``haiku``/``sonnet``) to a full model id, else pass through."""
    return MODEL_MAP.get(model, model)


def call_claude_p(
    prompt: str,
    model: str = "haiku",
    system: str | None = None,
    timeout: int = 180,
) -> str:
    """Run ``claude -p --model <id> <prompt>`` and return fence-stripped text.

    The model alias is resolved via :data:`MODEL_MAP`. ``claude -p`` is already
    authenticated in this environment, so no key export is needed.

    A ``system`` prompt (the v4 System section) overrides claude's default agentic
    persona so the model acts as the segmentation analyzer; ``--setting-sources``
    is emptied so the workspace's CLAUDE.md / settings are not applied.
    """
    model_id = resolve_model(model)
    cmd = ["claude", "-p", "--model", model_id, "--setting-sources", ""]
    if system:
        cmd += ["--system-prompt", system]
    cmd.append(prompt)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return strip_json_fence(result.stdout)


def mock_analyzer(prompt: str, model: str = "mock", system: str | None = None) -> str:
    """Deterministic offline analyzer: one segment covering the rendered history.

    Counts ``[type] ...`` history lines in the prompt and returns a single
    segment spanning all of them, so tests get >=1 segment per chunk with no
    network.
    """
    indices = list(range(_count_history_lines(prompt)))
    if not indices:
        indices = [0]
    segment = {
        "messageIndices": indices,
        "summary": "Mock segment covering the chunk.",
        "topic": "mock_topic",
        "subTopic": "mock subtopic",
        "sentiment": "neutral",
        "labelConfidence": 1.0,
        "botPromptCount": 0,
        "userResponseCount": len(indices),
    }
    return json.dumps({"segments": [segment]})


def _count_history_lines(prompt: str) -> int:
    """Count rendered ``[type] message`` history lines in a built prompt."""
    return sum(
        1 for line in prompt.splitlines() if re.match(r"^\s*\[[a-z_]+\]\s", line)
    )


def get_analyzer(name: str) -> Callable[..., str]:
    """Return the analyzer callable for ``name`` ("claude_p" | "mock")."""
    analyzers: dict[str, Callable[..., str]] = {
        "claude_p": call_claude_p,
        "mock": mock_analyzer,
    }
    try:
        return analyzers[name]
    except KeyError:
        raise ValueError(
            f"Unknown analyzer: {name!r}. Known: {sorted(analyzers)}"
        ) from None
