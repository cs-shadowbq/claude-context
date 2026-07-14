# claude-context

Fast search across your `~/.claude` world — conversations, plans, agents, and
memory — that tells you the one thing you usually need: **which project a hit
belongs to and the real filesystem path**, so you can open VSCode in the right
context.

Search is delegated to [ripgrep](https://github.com/BurntSushi/ripgrep) (fast,
unicode-aware); the JSON match stream is parsed and rendered with
[rich](https://github.com/Textualize/rich). Falls back to a pure-Python grep if
`rg` isn't installed.

## Install

Already installed:

- Tool: `~/.claude/tools/claude_context.py`
- Launcher: `~/bin/claude-context` (on your `PATH`)

Requires `python3` + `rich` (`python3 -m pip install rich`) and, ideally, `rg`.

## Usage

```bash
claude-context "can't stream responses"          # grouped summary by project
claude-context -v "polling"                       # verbose: every hit, full detail
claude-context -s -k memory "WebSocket"           # -s: whole enclosing markdown section
claude-context -j -k conversation "greenlight"    # -j: pretty-print the JSON/JSONL object
claude-context -k plan "watercolors"              # restrict to a kind (repeatable)
claude-context -i "gateway"                        # -i: case-insensitive (default: smart case)
claude-context -F "body::after"                    # -F: literal string, not regex
```

### Options

| Flag | Meaning |
|------|---------|
| `-v`, `--verbose` | Show every hit with full detail (project, real path, file, line). |
| `-s`, `--section` | For markdown hits, render the whole enclosing `#` section. |
| `-j`, `--json` | For conversation hits, pretty-print the full JSON/JSONL object. |
| `-i`, `--ignore-case` | Case-insensitive. Default is ripgrep smart case. |
| `-F`, `--fixed` | Treat the term as a literal string, not a regex. |
| `-k`, `--kind KIND` | Restrict to a source kind. Repeatable. |
| `--root PATH` | Override `CLAUDE_ROOT` (defaults to `~/.claude`). |

## Source kinds

Each hit is labeled and color-coded by where it came from:

| Kind | Where | Label |
|------|-------|-------|
| `conversation` | `projects/<enc>/*.jsonl` | Conversation |
| `project-memory` | `projects/<enc>/memory/*.md` | Project Memory |
| `memory` | `memory/*.md` | Memory |
| `agent-memory` | `agent-memory/<name>/*` | Agent Memory |
| `plan` | `plans/*.md` | Plan |
| `agent` | `agents/**/*.md` | Agent |

## How the "real path" is resolved

The encoded project dir name (`-Users-xxxxx-sandpit-…`) is **lossy** —
both `.` and `/` collapse to `-`, so it can't be reversed reliably. Instead, for
conversation and project-memory hits the tool reads the authoritative `cwd`
field embedded in the matching `.jsonl` line (or peeks at a sibling session file
when the hit is a project-memory `.md`). That `cwd` is the real path you open in
VSCode.

## Notes

- Verbose (`-v`) + a very broad term prints one panel per hit — use the default
  summary view or narrow with `-k` for broad terms.
- The default summary view groups hits by project/real-path and shows up to a
  handful of representative lines per group.
- `~0.6s` across all sources for a typical term; ripgrep does the heavy lifting
  and Python only parses matches.
