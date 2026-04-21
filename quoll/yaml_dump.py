"""Minimal, deterministic YAML emitter (GitHub workflows, GitLab pipelines, compose files).

quoll builds documents as plain dicts and emits them itself so the output is stable (byte-for-byte, which the
`check` commands rely on), readable and prettier-compatible.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List


class Commented(str):
    """A scalar followed by a comment, e.g. an action pinned to a commit, with its version."""

    comment: str

    def __new__(cls, value: str, comment: str) -> "Commented":
        obj = super().__new__(cls, value)
        obj.comment = comment
        return obj


_PLAIN_RE = re.compile(r"^[A-Za-z_][\w ./@()=,+-]*$")
_YAML_KEYWORDS = {"true", "false", "yes", "no", "on", "off", "null", "y", "n", "~"}
_RUN_UNSAFE_START = set("-?:,[]{}#&*!|>'\"%@`")


def dump(doc: Dict[str, Any], spaced: Iterable[str] = (), scripts: Iterable[str] = ("run",)) -> str:
    """YAML for `doc`; children of the `spaced` mappings are separated by a blank line, for readability.

    Values of the `scripts` keys are shell commands (a string or a list of them): emitted unquoted when YAML allows,
    as literal blocks otherwise.
    """
    lines: List[str] = []
    top_keys = list(doc)
    for i, key in enumerate(top_keys):
        if i:
            lines.append("")
        lines.extend(_emit_entry(key, doc[key], 0, frozenset(spaced), frozenset(scripts)))
    return "\n".join(lines) + "\n"


def _emit_entry(key: str, value: Any, indent: int, spaced: frozenset, scripts: frozenset) -> List[str]:
    pad = " " * indent
    if isinstance(value, Commented):
        return [f"{pad}{key}: {_scalar(str(value))} # {value.comment}"]
    if key in scripts and isinstance(value, list):
        out = [f"{pad}{key}:"]
        for command in value:
            out.extend(_emit_command(f"{pad}  - ", command, indent + 4))
        return out
    if key in scripts and isinstance(value, str):
        return _emit_command(f"{pad}{key}: ", value, indent + 2)
    if isinstance(value, dict):
        if not value:
            return [f"{pad}{key}: {{}}"]
        out = [f"{pad}{key}:"]
        for i, (k, v) in enumerate(value.items()):
            if i and key in spaced:
                out.append("")
            out.extend(_emit_entry(k, v, indent + 2, spaced, scripts))
        return out
    if isinstance(value, list):
        if all(not isinstance(v, (dict, list)) for v in value):
            return [f"{pad}{key}: [{', '.join(_scalar(v) for v in value)}]"]
        out = [f"{pad}{key}:"]
        for i, item in enumerate(value):
            if i and key in spaced:
                out.append("")
            out.extend(_emit_list_item(item, indent + 2, spaced, scripts))
        return out
    if value is None:
        return [f"{pad}{key}:"]
    if isinstance(value, str) and "\n" in value:
        return _block(f"{pad}{key}: ", value, indent + 2)
    return [f"{pad}{key}: {_scalar(value)}"]


def _emit_command(prefix: str, command: str, indent: int) -> List[str]:
    if "\n" in command or not _plain_run(command):
        return _block(prefix, command, indent)
    return [f"{prefix}{command}"]


def _block(prefix: str, text: str, indent: int) -> List[str]:
    pad = " " * indent
    return [f"{prefix}|", *(f"{pad}{line}" if line else "" for line in text.split("\n"))]


def _emit_list_item(item: Any, indent: int, spaced: frozenset, scripts: frozenset) -> List[str]:
    pad = " " * indent
    if not isinstance(item, dict):
        return [f"{pad}- {_scalar(item)}"]
    out: List[str] = []
    for i, (k, v) in enumerate(item.items()):
        entry = _emit_entry(k, v, indent + 2, spaced, scripts)
        if i == 0:
            entry[0] = f"{pad}- {entry[0].lstrip()}"
        out.extend(entry)
    return out


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    text = str(value)
    if text.startswith("${{") and ": " not in text and " #" not in text:
        return text
    if _plain_scalar(text):
        return text
    return json.dumps(text)


def _plain_scalar(text: str) -> bool:
    """Strings that read the same unquoted: start with a letter, no YAML indicators inside."""
    return (
        bool(_PLAIN_RE.match(text))
        and text.lower() not in _YAML_KEYWORDS
        and ": " not in text
        and " #" not in text
        and not text.endswith((":", " "))
    )


def _plain_run(cmd: str) -> bool:
    return (
        bool(cmd)
        and cmd[0] not in _RUN_UNSAFE_START
        and ": " not in cmd
        and " #" not in cmd
        and not cmd.endswith(":")
    )
