"""Named-prompt registry. Every LLM call uses a prompt loaded from ``prompts/`` by name
(CLAUDE.md §7) — no inline prompt strings in code, so prompts are reviewable and versioned
as data.

Resolution is **package-anchored**, not CWD-relative, so it works under Agent 4's CLI from
any directory and after merge to ``main``. ``HELIXPAY_PROMPTS_DIR`` overrides it for tests
and alternative packaging.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# extract/prompts.py -> extract -> ingest -> helixpay -> <repo root>/prompts
_PACKAGE_ANCHORED = Path(__file__).resolve().parents[3] / "prompts"

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


class PromptNotFoundError(KeyError):
    """Raised when a named prompt file does not exist in the prompts directory."""


def prompts_dir() -> Path:
    override = os.environ.get("HELIXPAY_PROMPTS_DIR")
    return Path(override) if override else _PACKAGE_ANCHORED


def available_prompts() -> list[str]:
    d = prompts_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.md"))


def load_prompt(name: str) -> str:
    path = prompts_dir() / f"{name}.md"
    if not path.is_file():
        raise PromptNotFoundError(
            f"prompt '{name}' not found at {path} (set HELIXPAY_PROMPTS_DIR to override)"
        )
    return path.read_text(encoding="utf-8")


def render(name: str, **variables: object) -> str:
    """Load a prompt and substitute ``{{var}}`` placeholders. Literal JSON braces in the
    template are left untouched (only the double-brace form is a placeholder), so the
    structured-output schema can be embedded verbatim. Unknown placeholders are left as-is.
    """
    text = load_prompt(name)

    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        return str(variables[key]) if key in variables else m.group(0)

    return _PLACEHOLDER_RE.sub(_sub, text)


__all__ = ["PromptNotFoundError", "available_prompts", "load_prompt", "render", "prompts_dir"]
