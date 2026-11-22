"""Reading a !run message (language, args, code block, stdin) and turning Piston's answer into chat text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

FENCE = re.compile(r"```(?:(?P<syntax>[^\s`]+)\n|\n?)(?P<source>.*?)```", re.S)
MAX_SOURCE = 65535


class RunError(Exception):
    """A problem with what the person sent, worded for them."""


@dataclass
class Job:
    language: str            # what they typed (an alias is fine)
    source: str
    args: list[str] = field(default_factory=list)
    stdin: str = ""
    output_syntax: str = ""


def parse(text: str, attachment: tuple[str, str] | None = None) -> Job:
    """``text`` is everything after ``!run``. ``attachment`` is (filename, its text) for a source file.

        !run python [-> syntax]
        arg one                      (optional, one per line)
        ```py
        code
        ```
        stdin lines                  (optional)
    """
    text = (text or "").strip("\n")
    head, _, rest = text.partition("\n")
    head = head.strip()
    language, output_syntax = head, ""
    if "->" in head:
        language, _, output_syntax = (p.strip() for p in head.partition("->"))
    if " " in language and "```" not in language:
        language = language.split()[0]
    m = FENCE.search(text)
    if attachment is not None:
        name, source = attachment
        if len(source) > MAX_SOURCE:
            raise RunError(f"That file is too big ({len(source):,} characters; the limit is {MAX_SOURCE:,}).")
        if not language or language.startswith("```"):
            if "." not in name:
                raise RunError("Give the language (`!run python`) or a file name with an extension.")
            language = name.rsplit(".", 1)[-1]
        lines = rest.split("\n") if rest else []
        args = [ln for ln in lines if ln.strip()]
        return Job(language.lower(), source, args, "", output_syntax)
    if not m:
        raise RunError("Put your code in a code block: three backticks before and after it.")
    if language.startswith("```"):
        language = ""
    language = (language or m.group("syntax") or "").lower()
    if " " in language:
        language = language.split()[0]
    if not language:
        raise RunError("Which language? `!run python` and then the code block, or start the block with ```python.")
    before = text[: m.start()]
    after = text[m.end():]
    arg_lines = before.split("\n")[1:]                       # lines between the command and the block
    args = [ln.strip() for ln in arg_lines if ln.strip()]
    source = m.group("source")
    if not source.strip():
        raise RunError("The code block is empty.")
    stdin = after.strip("\n")
    return Job(language, source, args, stdin, output_syntax)


def format_output(result: dict, label: str, max_lines: int = 30, max_chars: int = 1800) -> tuple[str, str]:
    """(kind, text) where kind is 'ok', 'stderr', 'compile' or 'empty'; text is ready for a code block."""
    comp = (result.get("compile") or {})
    comp_err = comp.get("stderr") or ""
    if comp.get("code") not in (None, 0) and not comp_err:
        comp_err = comp.get("output") or ""
    run = result.get("run") or {}
    output = (comp_err + (run.get("output") or "")).replace("\0", "")
    if not output.strip():
        return "empty", ""
    lines = output.rstrip("\n").split("\n")
    cut = len(lines) > max_lines
    output = "\n".join(lines[:max_lines])
    if len(output) > max_chars:
        output, cut = output[:max_chars], True
    output = output.replace("```", "`​``")              # keep the block closed
    if cut:
        output += "\n[...]"
    kind = "compile" if comp_err else ("stderr" if not (run.get("stdout") or "") and run.get("stderr") else "ok")
    return kind, output
