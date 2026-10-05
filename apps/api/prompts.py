"""Load prompts/*.md and fill {{variables}}. No prompt text lives in code."""

from __future__ import annotations

import re

from apps.api.settings import PROMPTS_DIR

_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class PromptError(KeyError):
    pass


def render(name: str, **variables: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    template = path.read_text()
    missing = {m.group(1) for m in _VAR.finditer(template)} - variables.keys()
    if missing:
        raise PromptError(f"prompt {name!r} needs variables: {sorted(missing)}")
    return _VAR.sub(lambda m: variables[m.group(1)], template)
