#!/usr/bin/env python3
"""claude-context — fast search across your ~/.claude world.

Finds a search term across conversations, plans, agents, and memory, then tells
you the one thing you usually need: *which project* the hit belongs to and the
*real path* so you can open VSCode in the right context.

Search is delegated to ripgrep (fast, respects unicode) and the JSON stream is
parsed and rendered with rich.

Usage:
    claude-context "can't stream responses"
    claude-context -v "polling"            # verbose: show every hit
    claude-context -s "gateway envelope"   # --section: whole markdown section
    claude-context --kind memory "CSP"     # restrict to one source kind
    claude-context -i "WebSocket"          # case-insensitive (default is smart)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.text import Text
except ImportError:
    sys.stderr.write(
        "This tool needs 'rich'. Install it with:  python3 -m pip install rich\n"
    )
    sys.exit(2)


CLAUDE_ROOT = Path(os.environ.get("CLAUDE_ROOT", Path.home() / ".claude"))

console = Console()


# --------------------------------------------------------------------------- #
# Source kinds — where we search and how to label a hit.
# --------------------------------------------------------------------------- #

# kind -> (relative glob dir, human label, is_conversation)
KINDS: dict[str, dict] = {
    "conversation": {
        "dirs": ["projects"],
        "globs": ["**/*.jsonl"],
        "label": "Conversation",
        "color": "cyan",
    },
    "project-memory": {
        # memory that lives *inside* a project dir
        "dirs": ["projects"],
        "globs": ["**/memory/*.md"],
        "label": "Project Memory",
        "color": "magenta",
    },
    "memory": {
        "dirs": ["memory"],
        "globs": ["*.md"],
        "label": "Memory",
        "color": "magenta",
    },
    "agent-memory": {
        "dirs": ["agent-memory"],
        "globs": ["**/*"],
        "label": "Agent Memory",
        "color": "bright_magenta",
    },
    "plan": {
        "dirs": ["plans"],
        "globs": ["*.md"],
        "label": "Plan",
        "color": "yellow",
    },
    "agent": {
        "dirs": ["agents"],
        "globs": ["**/*.md"],
        "label": "Agent",
        "color": "green",
    },
}


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class Hit:
    path: Path
    line_number: int
    line_text: str  # the raw matched line (may be a huge jsonl blob)
    kind: str
    submatches: list[tuple[int, int]] = field(default_factory=list)  # byte spans

    # Enriched lazily
    project_dir: str | None = None   # encoded dir name (…-Users-smacgregor-…)
    real_path: str | None = None     # decoded cwd from jsonl, or file's project
    snippet: str | None = None       # human-readable extract of the match


def label_for(kind: str) -> str:
    return KINDS[kind]["label"]


def color_for(kind: str) -> str:
    return KINDS[kind]["color"]


# --------------------------------------------------------------------------- #
# ripgrep driver
# --------------------------------------------------------------------------- #

def run_ripgrep(term: str, kinds: list[str], case_insensitive: bool,
                fixed: bool) -> list[Hit]:
    rg = shutil.which("rg")
    hits: list[Hit] = []

    # Build the file set per kind so we can attribute each hit to a kind.
    # We run rg once per (dir, glob) group but tag results by kind afterward
    # using path matching — simpler and still fast.
    globs: list[str] = []
    search_dirs: set[str] = set()
    for k in kinds:
        for d in KINDS[k]["dirs"]:
            search_dirs.add(d)
        for g in KINDS[k]["globs"]:
            globs.append(g)

    existing_dirs = [d for d in search_dirs if (CLAUDE_ROOT / d).exists()]
    if not existing_dirs:
        return hits

    if rg:
        cmd = [rg, "--json", "--no-heading"]
        if case_insensitive:
            cmd.append("-i")
        else:
            cmd.append("-S")  # smart case
        if fixed:
            cmd.append("-F")
        for g in globs:
            cmd += ["-g", g]
        cmd += [term]
        cmd += existing_dirs
        proc = subprocess.run(
            cmd, cwd=CLAUDE_ROOT, capture_output=True, text=True
        )
        # rg exits 1 when no matches — that's fine.
        for line in proc.stdout.splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "match":
                continue
            data = obj["data"]
            path = (CLAUDE_ROOT / data["path"]["text"]).resolve()
            spans = [
                (sm["start"], sm["end"]) for sm in data.get("submatches", [])
            ]
            hits.append(
                Hit(
                    path=path,
                    line_number=data["line_number"],
                    line_text=data["lines"]["text"].rstrip("\n"),
                    kind=classify_path(path),
                    submatches=spans,
                )
            )
    else:
        hits = python_grep(term, existing_dirs, globs,
                           case_insensitive, fixed)

    # Keep only hits whose classified kind was actually requested.
    return [h for h in hits if h.kind in kinds]


def python_grep(term, dirs, globs, case_insensitive, fixed) -> list[Hit]:
    """Pure-python fallback if ripgrep is missing."""
    import re
    flags = re.IGNORECASE if case_insensitive else 0
    pat = re.compile(re.escape(term) if fixed else term, flags)
    hits: list[Hit] = []
    seen: set[Path] = set()
    for d in dirs:
        base = CLAUDE_ROOT / d
        for g in globs:
            for path in base.glob(g):
                if not path.is_file() or path in seen:
                    continue
                seen.add(path)
                try:
                    with path.open("r", errors="replace") as fh:
                        for i, line in enumerate(fh, 1):
                            m = pat.search(line)
                            if m:
                                hits.append(Hit(
                                    path=path.resolve(),
                                    line_number=i,
                                    line_text=line.rstrip("\n"),
                                    kind=classify_path(path.resolve()),
                                    submatches=[(m.start(), m.end())],
                                ))
                except (OSError, UnicodeError):
                    continue
    return hits


def classify_path(path: Path) -> str:
    """Attribute a file path to a source kind, most-specific first."""
    try:
        rel = path.relative_to(CLAUDE_ROOT)
    except ValueError:
        rel = path
    parts = rel.parts
    s = str(rel)
    if parts and parts[0] == "projects":
        if "memory" in parts:
            return "project-memory"
        if path.suffix == ".jsonl":
            return "conversation"
    if parts and parts[0] == "agent-memory":
        return "agent-memory"
    if parts and parts[0] == "memory":
        return "memory"
    if parts and parts[0] == "plans":
        return "plan"
    if parts and parts[0] == "agents":
        return "agent"
    # default bucket
    return "conversation" if path.suffix == ".jsonl" else "memory"


# --------------------------------------------------------------------------- #
# Enrichment — the important part: figure out the real project path.
# --------------------------------------------------------------------------- #

def encoded_project_dir(path: Path) -> str | None:
    """Return the encoded project dir name (…-Users-…) for a hit path."""
    try:
        rel = path.relative_to(CLAUDE_ROOT / "projects")
    except ValueError:
        return None
    return rel.parts[0] if rel.parts else None


def real_path_from_jsonl_line(line_text: str) -> str | None:
    """A conversation line is a JSON object carrying the real `cwd`."""
    try:
        obj = json.loads(line_text)
    except json.JSONDecodeError:
        return None
    return obj.get("cwd") or obj.get("attachment", {}).get("cwd") if isinstance(
        obj.get("attachment"), dict) else obj.get("cwd")


def decode_project_dir(encoded: str) -> str:
    """Best-effort decode of the encoded dir back to a filesystem path.

    Note: encoding is lossy (dots and dashes both become '-'), so this is only
    a fallback. The `cwd` inside a jsonl line is authoritative.
    """
    # Leading '-Users-...' -> '/Users/...'
    return "/" + encoded.lstrip("-").replace("-", "/")


def enrich(hit: Hit) -> None:
    hit.project_dir = encoded_project_dir(hit.path)

    if hit.kind in ("conversation", "project-memory"):
        # Prefer the authoritative cwd embedded in the matched jsonl line.
        real = None
        if hit.kind == "conversation":
            real = real_path_from_jsonl_line(hit.line_text)
        if not real and hit.project_dir:
            # Peek at any line in the file to recover the real cwd.
            real = peek_cwd(hit.path)
        if not real and hit.project_dir:
            real = decode_project_dir(hit.project_dir)
        hit.real_path = real
    else:
        hit.real_path = str(hit.path)

    hit.snippet = build_snippet(hit)


_cwd_cache: dict[Path, str | None] = {}


def peek_cwd(path: Path) -> str | None:
    """For a project file, read the sibling jsonl to recover the real cwd."""
    if path in _cwd_cache:
        return _cwd_cache[path]
    result = None
    # If this is a jsonl itself, read its first cwd; else look at siblings.
    candidates = []
    if path.suffix == ".jsonl":
        candidates = [path]
    else:
        proj_root = path
        while proj_root.parent != (CLAUDE_ROOT / "projects") and \
                proj_root.parent != proj_root:
            proj_root = proj_root.parent
        candidates = sorted(proj_root.glob("*.jsonl"))
    for cand in candidates:
        try:
            with cand.open("r", errors="replace") as fh:
                for line in fh:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("cwd"):
                        result = obj["cwd"]
                        break
        except OSError:
            continue
        if result:
            break
    _cwd_cache[path] = result
    return result


def build_snippet(hit: Hit) -> str:
    """Produce a readable one-liner for the match."""
    if hit.kind == "conversation":
        return conversation_snippet(hit)
    # markdown / plain: trim the raw line
    text = hit.line_text.strip()
    return _center_on_match(text, hit)


def _center_on_match(text: str, hit: Hit, width: int = 200) -> str:
    if not hit.submatches:
        return text[:width]
    start = hit.submatches[0][0]
    lo = max(0, start - width // 2)
    hi = min(len(text), lo + width)
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(text) else ""
    return f"{prefix}{text[lo:hi]}{suffix}"


def conversation_snippet(hit: Hit) -> str:
    """Extract human text from a jsonl message line around the match."""
    try:
        obj = json.loads(hit.line_text)
    except json.JSONDecodeError:
        return _center_on_match(hit.line_text, hit)

    msg = obj.get("message")
    role = obj.get("type", "?")
    text = extract_text(msg) if msg is not None else ""
    if not text:
        # attachments (hooks, tool output) — summarize
        att = obj.get("attachment")
        if isinstance(att, dict):
            text = att.get("stdout") or att.get("content") or \
                att.get("command") or json.dumps(att)[:200]
    if not text:
        text = _center_on_match(hit.line_text, hit)

    # try to center on the search term within the extracted text
    return f"[{role}] {text.strip()[:400]}"


def extract_text(msg) -> str:
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                bt = block.get("type")
                if bt in ("text", "thinking"):
                    parts.append(block.get("text") or block.get("thinking", ""))
                elif bt == "tool_use":
                    inp = block.get("input", {})
                    parts.append(f"[tool:{block.get('name')}] "
                                 f"{json.dumps(inp)[:200]}")
                elif bt == "tool_result":
                    c = block.get("content")
                    parts.append(f"[tool_result] {extract_text({'content': c})}")
            return "\n".join(p for p in parts if p)
    return ""


# --------------------------------------------------------------------------- #
# Markdown section extraction (--section)
# --------------------------------------------------------------------------- #

def markdown_section(path: Path, line_number: int) -> str | None:
    """Return the whole markdown section (heading + body) containing a line."""
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    idx = line_number - 1
    if idx < 0 or idx >= len(lines):
        return None

    def heading_level(s: str) -> int | None:
        s2 = s.lstrip()
        if s2.startswith("#"):
            n = len(s2) - len(s2.lstrip("#"))
            if 1 <= n <= 6 and (len(s2) == n or s2[n] == " "):
                return n
        return None

    # Walk up to the nearest heading at/above the match.
    start = idx
    section_level = None
    while start >= 0:
        lvl = heading_level(lines[start])
        if lvl is not None:
            section_level = lvl
            break
        start -= 1
    if start < 0:
        start = 0

    # Walk down until a heading of same-or-higher rank.
    end = idx + 1
    while end < len(lines):
        lvl = heading_level(lines[end])
        if lvl is not None and section_level is not None and lvl <= section_level:
            break
        end += 1
    return "\n".join(lines[start:end]).strip()


# --------------------------------------------------------------------------- #
# JSON/JSONL pretty rendering (--json)
# --------------------------------------------------------------------------- #

def render_json_object(hit: Hit) -> Syntax | None:
    try:
        obj = json.loads(hit.line_text)
    except json.JSONDecodeError:
        return None
    pretty = json.dumps(obj, indent=2, ensure_ascii=False)
    return Syntax(pretty, "json", theme="ansi_dark",
                  word_wrap=True, background_color="default")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def highlight(text: str, term: str, case_insensitive: bool) -> Text:
    t = Text(text)
    t.highlight_words([term], "bold black on yellow",
                      case_sensitive=not case_insensitive)
    return t


def project_display(hit: Hit) -> tuple[str, str]:
    """Return (encoded_dir_or_dash, real_path_or_file)."""
    enc = hit.project_dir or "—"
    real = hit.real_path or str(hit.path)
    return enc, real


def render_summary(hits: list[Hit], term: str) -> None:
    """Group by project + kind and show the essentials the user asked for."""
    if not hits:
        console.print(f"[dim]No matches for[/] [bold]{term}[/]")
        return

    # Group by real project path (the thing you open in VSCode).
    groups: dict[str, list[Hit]] = {}
    for h in hits:
        key = h.real_path if h.kind in ("conversation", "project-memory") \
            else (h.project_dir or "(global)")
        # For global (non-project) kinds we group by kind label instead.
        if h.kind in ("plan", "agent", "memory", "agent-memory"):
            key = f"(global) {label_for(h.kind)}"
        groups.setdefault(key or "(unknown)", []).append(h)

    console.print(Rule(f"[bold]{len(hits)}[/] matches for "
                       f"[bold yellow]{term}[/] across "
                       f"[bold]{len(groups)}[/] locations"))

    for key, ghits in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        first = ghits[0]
        enc = first.project_dir
        color = color_for(first.kind)

        header = Text()
        if first.kind in ("conversation", "project-memory"):
            header.append("Found in Project: ", style="bold")
            header.append(f"{enc or '?'}\n", style=f"bold {color}")
            header.append("Path: ", style="bold")
            header.append(str(key), style="bold green underline")
        else:
            header.append(f"Found in {label_for(first.kind)}\n", style="bold")
            header.append(str(first.path.parent), style="green")

        body = Table.grid(padding=(0, 1))
        body.add_column(justify="right", style="dim", no_wrap=True)
        body.add_column(overflow="fold")

        # Show up to a handful of representative hits per group.
        shown = ghits[:6]
        for h in shown:
            loc = f"{label_for(h.kind)}"
            fname = h.path.name
            body.add_row(
                f"{loc}:",
                Text(fname, style=color_for(h.kind)),
            )
            body.add_row(
                f"(line {h.line_number})",
                highlight(h.snippet or "", term, True),
            )
        if len(ghits) > len(shown):
            body.add_row("", Text(f"… and {len(ghits) - len(shown)} more hits",
                                  style="dim italic"))

        console.print(Panel(body, title=header, title_align="left",
                            border_style=color, padding=(0, 1)))


def render_verbose(hits: list[Hit], term: str, show_section: bool,
                   show_json: bool) -> None:
    for i, h in enumerate(hits, 1):
        enc, real = project_display(h)
        color = color_for(h.kind)

        head = Text()
        head.append(f"[{i}/{len(hits)}] ", style="dim")
        head.append(f"{label_for(h.kind)}", style=f"bold {color}")
        console.print(Rule(head))

        meta = Table.grid(padding=(0, 2))
        meta.add_column(style="bold", justify="right")
        meta.add_column(overflow="fold")
        if h.kind in ("conversation", "project-memory"):
            meta.add_row("Project", Text(enc, style=color))
            meta.add_row("Real path", Text(real, style="green underline"))
        meta.add_row("File", Text(str(h.path), style="dim"))
        meta.add_row("Line", str(h.line_number))
        console.print(meta)

        if show_json and h.kind == "conversation":
            syn = render_json_object(h)
            if syn:
                console.print(Panel(syn, title="JSON line",
                                   border_style="cyan"))
                continue

        if show_section and h.path.suffix == ".md":
            section = markdown_section(h.path, h.line_number)
            if section:
                console.print(Panel(Markdown(section),
                                   title="Section", border_style=color))
                continue

        console.print(Panel(highlight(h.snippet or "", term, True),
                            border_style=color))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="claude-context",
        description="Search ~/.claude and find the project + real path for a "
                    "conversation, plan, agent, or memory.",
    )
    p.add_argument("term", help="text or regex to search for")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="show every hit with full detail")
    p.add_argument("-s", "--section", action="store_true",
                   help="for markdown hits, render the whole enclosing section")
    p.add_argument("-j", "--json", action="store_true",
                   help="for conversation hits, pretty-print the JSON line")
    p.add_argument("-i", "--ignore-case", action="store_true",
                   help="case-insensitive (default: smart case)")
    p.add_argument("-F", "--fixed", action="store_true",
                   help="treat term as a literal string, not a regex")
    p.add_argument("-k", "--kind", action="append", choices=list(KINDS),
                   help="restrict to one or more source kinds (repeatable)")
    p.add_argument("--root", help="override CLAUDE_ROOT")
    args = p.parse_args(argv)

    global CLAUDE_ROOT
    if args.root:
        CLAUDE_ROOT = Path(args.root).expanduser().resolve()
    if not CLAUDE_ROOT.exists():
        console.print(f"[red]CLAUDE_ROOT not found:[/] {CLAUDE_ROOT}")
        return 2

    kinds = args.kind or list(KINDS)

    with console.status(f"Searching for [bold]{args.term}[/]…", spinner="dots"):
        hits = run_ripgrep(args.term, kinds, args.ignore_case, args.fixed)
        for h in hits:
            enrich(h)

    if args.verbose:
        render_verbose(hits, args.term, args.section, args.json)
        console.print(Rule(f"[dim]{len(hits)} matches[/]"))
    else:
        render_summary(hits, args.term)

    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
