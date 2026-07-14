#  Claude Context — fast search across your ~/.claude world.

Finds a search term across conversations, plans, agents, and memory, then tells
you the one thing you usually need: *which project* the hit belongs to and the
*real path* so you can open VSCode in the right context.

Search is delegated to ripgrep (fast, respects unicode) and the JSON stream is
parsed and rendered with rich. Machine-readable output modes make this tool
usable by an LLM (including Claude itself) as a cheap recall step before
deciding whether it's worth spending tokens reading full files.

## Install

Requires `python3` + `rich` (`python3 -m pip install rich`) and, ideally, `rg`.

## Usage

```bash
Usage:
    claude-context "can't stream responses"
    claude-context -v "polling"                     # verbose: show every hit
    claude-context -s "gateway envelope"             # --section: whole markdown section
    claude-context --kind memory "CSP"                # restrict to one source kind
    claude-context -i "WebSocket"                     # case-insensitive (default is smart)
    claude-context "gateway" -e "envelope"            # AND: both terms on the line
    claude-context "gateway" -e "envelope" --term-logic or
    claude-context -C 3 "panic"                       # 3 lines of context
    claude-context --since 3d "deploy"                # last 3 days
    claude-context --before 2026-07-01 "deploy"
    claude-context -l "gateway" | xargs -I{} code {}  # paths only, for piping
    claude-context -o "gateway envelope"              # open best match in editor

    # LLM / low-token workflows:
    claude-context "reconnect jitter" --format compact   # grep-able one-liner output
    claude-context "reconnect jitter" --format json       # structured, for tool calls
    claude-context "reconnect jitter"                     # note the [id] shown per hit
    claude-context --expand a1b2c3d4                      # re-hydrate ONE cached hit fully
    claude-context --expand 2                              # or by index from the last run
    claude-context --related a1b2c3d4                      # find similar content elsewhere
    claude-context --related ~/.claude/memory/foo.md        # ...without knowing exact wording
    claude-context "gateway envelope" --recall               # cross-project comparison view
    claude-context "gateway envelope" --stats                 # counts only, no content
    claude-context --list --kind memory                       # browse memories, no search
    claude-context --list --tag websocket                     # browse by tag
    claude-context "gateway" --tag backend --unique --budget 2000
```

### Options

```bash
usage: claude-context [-h] [-e EXTRA_TERM] [--term-logic {and,or}] [-v] [-s] [-j] [-i] [-F] [-k {conversation,project-memory,memory,agent-memory,plan,agent}] [-C CONTEXT] [--since SINCE] [--before BEFORE] [-n MAX_RESULTS] [--sort {count,recent,score}] [-l] [-o]
                      [-x EXCLUDE] [--root ROOT] [--debug] [--format {rich,json,jsonl,compact}] [--expand ID|INDEX] [--list] [--tag TAG] [--unique] [--budget BUDGET] [--recall] [--stats] [--related ID|INDEX|PATH]
                      [term]

Search ~/.claude and find the project + real path for a conversation, plan, agent, or memory.

positional arguments:
  term                  text or regex to search for

options:
  -h, --help            show this help message and exit
  -e EXTRA_TERM, --extra-term EXTRA_TERM
                        additional term to search for (repeatable)
  --term-logic {and,or}
                        how multiple terms combine (default: and)
  -v, --verbose         show every hit with full detail
  -s, --section         for markdown hits, render the whole enclosing section
  -j, --json            for conversation hits, pretty-print the JSON line
  -i, --ignore-case     case-insensitive (default: smart case)
  -F, --fixed           treat term as a literal string, not a regex
  -k {conversation,project-memory,memory,agent-memory,plan,agent}, --kind {conversation,project-memory,memory,agent-memory,plan,agent}
                        restrict to one or more source kinds (repeatable)
  -C CONTEXT, --context CONTEXT
                        show N lines of context around each hit
  --since SINCE         only hits at/after this time (e.g. 2026-07-01, 3d, 12h)
  --before BEFORE       only hits before this time
  -n MAX_RESULTS, --max-results MAX_RESULTS
                        cap the number of hits processed/shown
  --sort {count,recent,score}
                        group ordering (default: score)
  -l, --paths-only      print matching real paths only, one per line (for piping)
  -o, --open            open the best-matching project/file in your editor
  -x EXCLUDE, --exclude EXCLUDE
                        glob pattern to exclude (repeatable)
  --root ROOT           override CLAUDE_ROOT
  --debug               print the underlying ripgrep command
  --format {rich,json,jsonl,compact}
                        output format — use json/jsonl/compact for LLM/tool consumption
  --expand ID|INDEX     re-hydrate one hit from the last search into full detail
  --list                browse memories/plans/agents without a search term
  --tag TAG             filter to hits/entries with this frontmatter tag (repeatable)
  --unique              collapse near-duplicate hits (same lesson copied across files)
  --budget BUDGET       cap total estimated output tokens (keeps highest-scoring hits)
  --recall              cross-project comparison view: where have I dealt with this before?
  --stats               counts only, no content — quick sanity check before a full pull
  --related ID|INDEX|PATH
                        find content related to a prior hit or file, without exact wording
```

## Config (Optional)

CLI flags always override the config file.

```bash
 $> ~/.config/claude-context/config.json
    {
      "root": "~/.claude",
      "kinds": ["conversation", "memory"],
      "exclude": ["projects/**/node_modules/**"],
      "context": 2,
      "max_results": 500,
      "sort": "score",
      "term_logic": "and",
      "format": "rich"
    }
```

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

## Example

Here's a concrete walkthrough of `--recall`, both as a human sees it and as an LLM would consume it.

### The scenario
You're in a new project and think: *"I remember fixing a WebSocket reconnect storm somewhere before — where?"*

```bash
claude-context "websocket reconnect" --recall
```

### Human output (rich table)

```
Recall: websocket reconnect — 4 location(s)
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Id      ┃ Project/Location                         ┃ Kind            ┃ Date       ┃ Score ┃ Hits ┃ Takeaway                                   ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ a1b2c3d4│ /Users/xxxxxx/dev/gateway-service        │ Project Memory  │ 2026-05-02 │ 4.8   │ 3    │ Added jittered exponential backoff before  │
│         │                                          │                 │            │       │      │ reconnect to avoid thundering herd on...   │
│ 7f9e2a10│ /Users/xxxxxx/dev/csp-detect-eng         │ Conversation    │ 2026-03-18 │ 3.1   │ 6    │ [assistant] The websocket kept reconnecting│
│         │                                          │                 │            │       │      │ every 200ms because the retry loop had no  │
│ 4c8d1e22│ (global) Memory                          │ Memory          │ 2026-06-30 │ 2.6   │ 1    │ General note: always cap retry backoff at  │
│         │                                          │                 │            │       │      │ 30s and add ±20% jitter for any long-lived │
│ b3a7f019│ /Users/xxxxxx/dev/old-poc-agent          │ Conversation    │ 2025-11-04 │ 1.2   │ 2    │ [user] can we just add a sleep(1) before   │
│         │                                          │                 │            │       │      │ retrying the socket                        │
└─────────┴──────────────────────────────────────────┴─────────────────┴────────────┴───────┴──────┴────────────────────────━━━─────────────────┘
Use --expand <id> for full detail, or --related <id> to dig deeper.
```

At a glance: the real answer is almost certainly `a1b2c3d4` (`gateway-service`, curated project memory, highest score, most recent, on-topic). You'd run:

```bash
claude-context --expand a1b2c3d4 -s
```

and get the full markdown section with the actual backoff/jitter implementation notes.

## Same query, LLM-consumable

```bash
claude-context "websocket reconnect" --recall --format json
```

```json
{
  "count": 12,
  "hits": [
    {
      "id": "a1b2c3d4",
      "kind": "project-memory",
      "label": "Project Memory",
      "path": "/Users/xxxxxx/.claude/projects/-Users-smacgregor-dev-gateway-service/memory/reconnect-strategy.md",
      "real_path": "/Users/xxxxxx/dev/gateway-service",
      "project_dir": "-Users-xxxxxx-dev-gateway-service",
      "line": 14,
      "snippet": "## Reconnect backoff\nAdded jittered exponential backoff before reconnect to avoid thundering herd on gateway restarts...",
      "score": 4.8,
      "tags": ["websocket", "resilience"],
      "epoch": 1746201600.0,
      "date": "2026-05-02T00:00:00",
      "tokens_est": 61
    },
    { "id": "7f9e2a10", "kind": "conversation", "score": 3.1, "...": "..." },
    { "id": "4c8d1e22", "kind": "memory", "score": 2.6, "...": "..." },
    { "id": "b3a7f019", "kind": "conversation", "score": 1.2, "...": "..." }
  ]
}
```

Note: `--recall --format json` currently falls back to the flat `render_machine` hit list rather than the grouped recall table — that's a gap worth closing (see note at the end).

### How Claude would actually use this mid-conversation

This is the intended tool-call loop — cheap search first, expensive read only once:

**Turn 1 — user asks:** *"Have we dealt with websocket reconnect issues before? I'm hitting one in project X."*

**Claude's internal steps:**

1. **Recall pass (cheap, ~200 tokens of output):**
   ```bash
   claude-context "websocket reconnect" --recall --format json -n 10
   ```
   Claude parses the JSON, sorts by `score`, and reasons: *"top hit is `a1b2c3d4`, a curated project-memory entry in `gateway-service`, score 4.8, recent — that's almost certainly the answer, not the noisy conversation hits."*

2. **Expand only the winner (still cheap, targeted):**
   ```bash
   claude-context --expand a1b2c3d4 --format json
   ```
   This returns the full markdown section — the actual backoff algorithm, thresholds, code snippet — without ever loading the other 3 candidates or the surrounding conversation logs.

3. **Optional follow-up if the top hit is thin:**
   ```bash
   claude-context --related a1b2c3d4 --format json
   ```
   Pulls TF-based keywords (`jitter`, `backoff`, `thundering`, `restart`) from that memory and searches for them elsewhere — catching cases where the *same lesson* was independently rediscovered and documented differently in another project, even without shared exact phrasing.

4. **Claude responds to the user:**
   > "Yes — you solved this in `gateway-service` back in May: jittered exponential backoff capped at 30s to avoid a reconnect storm after gateway restarts. Here's the approach... want me to port it into project X?"

**Total token cost:** one ~1–2KB JSON recall listing + one ~1KB expand payload, instead of grep-ing/opening 4 full conversation transcripts (which could easily be tens of thousands of tokens each) to manually figure out which one was relevant.


