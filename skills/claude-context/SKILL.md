---
name: claude-context
description: >
  Search across all ~/.claude data (conversations, project memories, global
  memories, plans, agents) to find prior work, past solutions, and relevant
  context before reading raw files or grepping manually. Use this whenever
  the user asks things like "have we dealt with this before," "did I solve
  this somewhere," "find that memory/note about X," "what project was that
  in," or when you (Claude) need to recall a prior decision, convention, or
  fix across projects without knowing which project or conversation it's in.
  Always prefer this tool over `grep`/`find`/reading whole .claude files
  directly — it is dramatically cheaper in tokens and returns structured,
  rankable results.
---

# claude-context

A ripgrep-backed search tool over `~/.claude` (conversations, project
memories, global memories, plans, agents). It resolves the *real* project
path for a hit and scores/ranks results, so you don't have to open large
files to figure out relevance.

Script: `~/.claude/tools/src/claude_context.py`
Invoke as: `claude-context <args>` (assume it's on PATH; if not, run
`python3 ~/.claude/tools/src/claude_context.py <args>`).

## Core principle: two-phase search, not full-file reads

**Never** read a raw `.jsonl` conversation file or a whole memory directory
to "look for" something — it burns enormous context for low signal. Instead:

1. **Recall pass** (cheap): search with `--format json` to get ranked
   candidates (id, score, snippet, path, tags) — a few hundred tokens.
2. **Expand pass** (targeted): once you've identified the right hit,
   `--expand <id>` to pull the *full* section/content of just that one hit.

This mirrors how you'd want a human to work too: shortlist first, deep-dive
only on the winner.

## When to use which mode

| Situation | Command |
|---|---|
| "Have I dealt with X before, but I don't know where?" | `claude-context "X" --recall --format json` |
| Know the exact phrase, want ranked hits | `claude-context "X" --format json` |
| Found a promising hit, want full content | `claude-context --expand <id> --format json` |
| Remember the *idea* but not the wording | `claude-context --related <id-or-path> --format json` |
| Just want to browse what memories/plans exist | `claude-context --list --kind memory --format json` |
| Want a quick sense of scale before committing | `claude-context "X" --stats` |
| Need both terms present, not either | `claude-context "X" -e "Y" --term-logic and --format json` |
| Only care about a time window | `claude-context "X" --since 30d --format json` |
| Piping the real project path onward | `claude-context "X" -l` |

## Output format

**Always pass `--format json` (or `jsonl`/`compact`) when calling this tool
yourself** — the default `rich` output is for humans in a terminal and is
wasteful/unparseable for you. Key fields per hit:

- `id` — short hash handle; pass to `--expand`/`--related`
- `kind` — `conversation | project-memory | memory | agent-memory | plan | agent`
- `real_path` — the actual filesystem project directory (for conversation/project-memory hits) — this is what the user means by "which project"
- `score` — relevance (frequency × kind-weight × recency × tag bonus); curated memory outranks raw conversation noise
- `snippet`, `tags`, `date`, `tokens_est`

## Example workflow

User: *"Did we already figure out a fix for websocket reconnect storms?"*

```bash
claude-context "websocket reconnect" --recall --format json -n 10
```

→ parse JSON, pick highest-score hit (prefer kind: memory /
project-memory over conversation).

```bash
claude-context --expand <winning-id> --format json
```

→ read the full section/content, then answer the user with the actual
prior solution and its source project (real_path).

If the top hits look thin or off-topic, broaden with:

```bash
claude-context --related <winning-id> --format json
```

which re-searches using keywords extracted from that hit — useful when the
original phrasing doesn't match what the user is asking now.

## Other useful flags
-k/--kind — restrict to one or more of: conversation, project-memory,
memory, agent-memory, plan, agent
-i case-insensitive, -F literal string (not regex)
-C N — N lines of context around a hit
--tag <tag> — filter by frontmatter tag (memory/plan/agent files)
--unique — collapse duplicate lessons copy-pasted across projects
--budget N — cap total estimated output tokens (keeps top-scoring hits)
--since/--before — 2026-07-01, or relative (3d, 12h, 2w)
-o/--open — opens the best-matching path in $EDITOR (human use)

## Do NOT
Do not use grep -r, find, or cat/Read on ~/.claude/projects/** or
~/.claude/memory/** directly — always go through this tool first.

Do not request --format rich for your own tool calls — it's decorative
and costs more tokens to parse than it's worth.

Do not skip the recall pass and jump straight to --expand on a guess 
—always confirm the id via a search/recall call first.
