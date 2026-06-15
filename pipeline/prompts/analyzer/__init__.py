"""
Versioned Analyzer prompts.

Each version is a Markdown file (eb1_prompt_user_v1.md, ...) with two sections:

  ## System   — the system prompt text (no placeholders)
  ## User     — the user prompt template (may contain {placeholders})

Config controls which version is loaded:
  analyzer.toml → [analyzer] → prompt_version = "latest" | "v1" | "v2" | ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent


@dataclass
class PromptTemplate:
    version: str
    system: str          # raw system prompt text
    user_template: str   # user prompt with {placeholders}

    def build_system_prompt(self) -> str:
        return self.system

    def build_user_prompt(self, **kwargs) -> str:
        return self.user_template.format(**kwargs)


def load_prompt(version: str = "latest", kind: str = "user") -> PromptTemplate:
    """Load a versioned .md prompt template.

    Args:
        version: "latest" (or empty) resolves to the highest vN.md.
                 Otherwise, a specific version like "v1", "v2", "v3".
        kind: "user" or "bot" — determines which prompt file family to load.

    Returns:
        A PromptTemplate with build_system_prompt() and build_user_prompt().
    """
    if not version or version == "latest":
        version = _find_latest_version(kind)

    # Strip legacy "bot_" prefix if present (e.g. "bot_v1" → "v1")
    if version.startswith("bot_"):
        version = version[4:]

    md_path = _PROMPT_DIR / f"eb1_prompt_{kind}_{version}.md"
    if not md_path.exists():
        raise FileNotFoundError(
            f"Prompt {kind}/{version} not found. "
            f"Expected file: {md_path}"
        )

    return _parse_prompt_file(md_path, version)


def _find_latest_version(kind: str = "user") -> str:
    """Scan for eb1_prompt_{kind}_vN.md files and return the highest version string."""
    pattern = re.compile(rf"^eb1_prompt_{kind}_v(\d+)\.md$")
    versions: list[tuple[int, str]] = []
    for f in _PROMPT_DIR.iterdir():
        m = pattern.match(f.name)
        if m:
            versions.append((int(m.group(1)), f"v{m.group(1)}"))
    if not versions:
        raise FileNotFoundError(
            f"No versioned {kind} prompt files "
            f"(eb1_prompt_{kind}_v1.md, ...) found in {_PROMPT_DIR}"
        )
    versions.sort()
    return versions[-1][1]


def _parse_prompt_file(path: Path, version: str) -> PromptTemplate:
    """Read a .md prompt file and split into system and user sections.

    Accepted section headers (first match wins):
      System: '## System' or '## Role'
      User:   '## User' or '## Context'

    Text between the system header and the user header becomes the system prompt.
    Text after the user header becomes the user template.
    Leading/trailing whitespace is stripped from each section.
    """
    text = path.read_text(encoding="utf-8")

    system_match = (
        re.search(r"^## System\s*$", text, re.MULTILINE)
        or re.search(r"^## Role\s*$", text, re.MULTILINE)
    )
    user_match = (
        re.search(r"^## User\s*$", text, re.MULTILINE)
        or re.search(r"^## Context\s*$", text, re.MULTILINE)
    )

    if not system_match:
        raise ValueError(
            f"Prompt file {path} is missing a system section (## System or ## Role)."
        )
    if not user_match:
        raise ValueError(
            f"Prompt file {path} is missing a user section (## User or ## Context)."
        )

    system_start = system_match.end()
    user_start = user_match.end()

    if system_start > user_start:
        raise ValueError(
            f"Prompt file {path}: system section must appear before user section."
        )

    system_text = text[system_start:user_match.start()].strip()
    user_text = text[user_start:].strip()

    return PromptTemplate(
        version=version,
        system=system_text,
        user_template=user_text,
    )
