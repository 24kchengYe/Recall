\![Visitors](https://visitor-badge.laobi.icu/badge?page_id=24kchengYe.claude-code-recall)
# Recall — Never Lose a Claude Code Conversation Again

> **Cross-project session manager with category organization, version history, and anti-compaction backup — without sacrificing Claude Code's security model.**

## Why Recall?

There are two extremes in AI coding assistants today:

**OpenClaw** gives you full-computer autonomy — persistent memory across days, browser automation, 700+ skills, 24/7 background agents. But it runs with **elevated system permissions, no sandbox, and autonomous command execution**. Cisco's AI security team found community skills performing [data exfiltration without user awareness](https://www.unite.ai/openclaw-vs-claude-code-remote-control-agents/). As one developer put it: *"OpenClaw is basically Claude Code without the corporate safety guardrails."*

**Claude Code** takes the opposite approach — sandboxed execution, human approval for critical operations, project-scoped isolation. Secure by design. But this means **conversations are locked to individual project directories**. You can't see, search, or resume sessions from other projects. Every project is an island.

**Recall bridges this gap.** It adds cross-project session management, persistent organization, and long-term memory — all while keeping Claude Code's permission model and security guarantees intact. No elevated permissions, no background processes, no autonomous execution. Just a lightweight index layer on top of Claude Code's native storage.

```
┌─────────────────────────────────────────────────────────────┐
│              Security ◄──────────────► Capability           │
│                                                             │
│  Claude Code          Recall              OpenClaw          │
│  (project-scoped)     (cross-project)     (full-computer)   │
│  ■■■■■■■■■■          ■■■■■■■■■           ■■■■              │
│  Security             Security             Security          │
│  ■■■■                ■■■■■■■■             ■■■■■■■■■■        │
│  Memory scope         Memory scope         Memory scope      │
└─────────────────────────────────────────────────────────────┘
```

## The Problem Recall Solves

Claude Code stores conversation history **per project directory** (`~/.claude/projects/<path>/`). This means:

- Sessions from **Project A are invisible** when you're working in **Project B**
- Built-in `/resume` only shows sessions from the **current** directory
- No way to organize conversations by topic — they're locked to whichever folder you opened
- No cross-project knowledge transfer between related conversations
- No central place to find "that conversation from last week"

This is true across VS Code, JetBrains, Cursor, Windsurf, and terminal CLI.

## What Recall Does

Recall creates a **centralized session index** — a management layer that maps to original session files while keeping backup copies organized by user-defined categories.

```
~/claude-sessions/                ← Central directory (configurable)
├── _config.json                  ← Categories & settings
├── 论文/
│   ├── BSAS论文修改_meta.json    ← Metadata + mapping to original
│   └── BSAS论文修改.jsonl        ← Full session backup
├── 代码/
│   ├── WebApp重构_meta.json
│   └── WebApp重构.jsonl
└── 学习/
```

**Key design**: Recall is a **read-mostly index layer**, not a replacement for Claude Code's native storage. It preserves Claude Code's security model — no elevated permissions, no background processes, no autonomous execution.

## Commands

| Command | Description |
|---------|-------------|
| `/recall` | Show interactive action menu |
| `/recall save` | Save current session (with auto-summary v2.0) |
| `/recall search <query>` | **v2.0** Semantic search (embedding-based + keyword fallback) |
| `/recall context` | **v2.0** Smart context injection (auto-retrieve relevant history) |
| `/recall browse` | Visual hierarchical browsing (categories → sessions → actions) |
| `/recall list` | List all saved sessions in a table |
| `/recall list search <keyword>` | Search sessions by name, summary, or tags |
| `/recall list recent [N]` | Show N most recently modified sessions |
| `/recall list stats` | Statistics overview (counts, categories, largest session) |
| `/recall load` | Load a past session as reference context in current conversation |
| `/recall resume` | Find and resume a session from any project |
| `/recall rename` | Rename a session (bidirectional sync with original project) |
| `/recall move` | Move session to a different category |
| `/recall history` | View version history, compare, or rollback a session |
| `/recall manage` | Manage categories (add, remove, view stats) |
| `/recall reindex` | **v2.0** Regenerate all summaries + rebuild search index |
| `/recall notify setup` | **v2.0** Configure WeChat notifications via Server酱 |

## Core Features

### Save & Organize
Save any conversation to a central location with a custom name and category. Default categories: 学习, 生活, 代码, 算法, 论文, 工作, 杂项 — fully customizable.

**Auto-update**: Save a session once, then `/recall save` again anytime for a fresh snapshot — no re-selection needed. Recall detects the existing backup by session ID and silently updates it.

**Auto-save on exit (v2.0)**: Sessions that have been saved at least once are automatically updated when you exit Claude Code (via `SessionEnd` hook). No manual save needed for already-tracked sessions.

**Auto-summary (v2.0)**: Every save generates a structured summary and tags from the session content — extracted topics, files touched, tools used. Pure rule-based, no LLM API cost.

**Filesystem-first detection**: Recall identifies the current session by filesystem modification time, not `sessions-index.json` (which can be stale). This ensures accurate detection even when Claude Code hasn't updated its own index.

### Cross-Project Context Loading (`/recall load`)
The killer feature. Load content from a past conversation into your **current** session as reference context. Two modes:
- **Brief**: User questions + assistant text answers only
- **Detailed**: Includes tool usage summaries (which files were edited, what commands ran)

This enables cross-project knowledge transfer — discuss an algorithm in Project A, then load that context while working in Project B. Like OpenClaw's persistent memory, but on-demand and without background token consumption.

### Interactive Browse (`/recall browse`)
Visual, clickable hierarchical navigation designed for hundreds of sessions:
1. **Layer 1**: Category overview (with session counts)
2. **Layer 2**: Session list within a category (paginated, 3 per page)
3. **Layer 3**: Session detail + executable actions (load, resume, rename, move)

### Version History & Anti-Compaction (`/recall history`)
The central directory is a git repository. Every `/recall save` auto-commits a snapshot, giving you full version history:
- **View history**: See every save point with timestamp and message count
- **Compare versions**: See how a conversation grew between two saves
- **Rollback**: Restore any historical version — the current version is never lost
- **Anti-compaction**: Claude Code compresses long conversations, permanently losing early messages. Frequent `/recall save` captures the full conversation before compaction happens. If compaction truncates your session, rollback to a pre-compaction snapshot to recover the complete history.

### Search & Statistics
- **Search**: Find sessions by keyword across name, summary, first prompt, and tags
- **Recent**: Quick view of your N most recently modified sessions
- **Stats**: Overview of total sessions, messages, per-category counts, most active category, largest session

### Semantic Search (v2.0)
Go beyond keyword matching. `/recall search` uses OpenAI embeddings (`text-embedding-3-small`, ~$0.02/M tokens) to find sessions by meaning, not just exact words. Ask "last week's bug discussion" and get results even if you never used those exact words. Falls back to smart keyword search when no API key is configured.

### Smart Context Injection (v2.0)
Say "根据之前的讨论" or use `/recall context` — Recall automatically retrieves the top-3 most relevant historical sessions and injects their summaries (~600 tokens total) into your current conversation. Like having a memory that remembers what you discussed across all projects.

### Task Completion Notifications (v2.0)
Configure WeChat notifications via Server酱 (free). When a Claude Code task is marked complete, get a push notification on your phone. Never miss a long-running task finishing. Setup: `/recall notify setup`.

### Resume from Anywhere
Select a session from any project, and Recall handles the rest:

- **Same project**: Shows the `claude --resume` command directly
- **Different project**: Opens a **new VSCode window** or **new terminal** at the target project, with the resume command ready to paste
- **Original deleted**: Restores from backup first, then provides the resume command

No more hunting through directories to find where a conversation lives.

### Bidirectional Rename
When you rename a session in Recall, it updates **both** the central index and the original project's `sessions-index.json`. No desync between what Recall shows and what `/resume` shows.

## Recall vs. OpenClaw vs. Built-in

| Capability | Built-in `/resume` | Recall | OpenClaw |
|---|---|---|---|
| Cross-project sessions | No | Yes | Yes |
| Organize by category | No | Yes | Partial |
| Search all conversations | No | Yes (semantic v2.0) | Yes |
| Load past context | No | Yes | Yes (persistent) |
| Smart context injection | No | Yes (v2.0) | Yes |
| Auto-save on exit | No | Yes (v2.0 hook) | Yes |
| Session summaries | No | Yes (v2.0 auto) | Partial |
| Task notifications | No | Yes (v2.0 WeChat) | Partial |
| Resume from any directory | No | Yes | Yes |
| Central backup | No | Yes | Yes |
| Version history & rollback | No | Yes (git) | No |
| Anti-compaction | No | Yes | Partial |
| Sandboxed execution | Yes | Yes | **No** |
| Human approval required | Yes | Yes | **No** |
| No background processes | Yes | Yes | **No** |
| No elevated permissions | Yes | Yes | **No** |
| Works offline | Yes | Yes | Partial |
| Zero extra API cost | Yes | Yes* | **No** (24/7 tokens) |

\* Semantic search optionally uses OpenAI embeddings (~$0.02/M tokens, negligible cost). All other features are zero-cost.

## Installation

### From Skills CLI (Recommended)

```bash
npx skills add 24kchengYe/claude-code-recall
```

### Manual Installation

```bash
# macOS / Linux
git clone https://github.com/24kchengYe/claude-code-recall.git ~/.claude/skills/recall

# Windows
git clone https://github.com/24kchengYe/claude-code-recall.git %USERPROFILE%\.claude\skills\recall
```

## Requirements

- Claude Code (VS Code, JetBrains, Cursor, Windsurf, or terminal CLI)
- Python 3.8+ (for the helper script that parses `.jsonl` session files)
- Git (for version history — auto-initialized on first save)

## Configuration

On first `/recall save`, Recall initializes:
- **Storage path**: Default `~/claude-sessions/` — you'll be prompted to confirm or customize
- **Categories**: Default set provided, fully customizable via `/recall manage`

All settings stored in `<basePath>/_config.json`.

## How Claude Code Stores Sessions (Background)

For those curious about the internals:

- Each project maps to a directory: `~/.claude/projects/<encoded-path>/`
- Sessions are stored as `.jsonl` files (one JSON object per line)
- A `sessions-index.json` per project tracks session metadata (but is often stale — not all sessions are indexed)
- Message types include: `user`, `assistant`, `system`, `progress`, and more
- Context compression creates `compact_boundary` markers in long sessions

Recall reads these native files and builds an index on top of them — it doesn't replace Claude Code's storage, just adds a cross-project management layer. When `sessions-index.json` is stale, Recall falls back to filesystem modification times for reliable session detection.

## Changelog

### v2.0.0 — 2026-03-03

- **feat**: Auto-save via `SessionEnd` hook — previously saved sessions auto-update on exit
- **feat**: Session summary generation — structured summaries + tags extracted from JSONL content
- **feat**: Semantic search with OpenAI embeddings (`/recall search`) — cosine similarity over session embeddings, keyword fallback
- **feat**: Smart context injection (`/recall context`) — auto-retrieve relevant history based on current conversation topic
- **feat**: WeChat task completion notifications via Server酱 (`/recall notify setup`) — `TaskCompleted` hook integration
- **feat**: Reindex command (`/recall reindex`) — batch regenerate summaries and rebuild search index for all sessions
- **feat**: SQLite search index (`_index.sqlite`) for fast embedding-based retrieval

### v1.5.0 — 2026-03-03

- **feat**: Git-based version history — central directory is now a git repo, every save/rename/move auto-commits
- **feat**: Add `/recall history` command — view version timeline, compare versions, rollback to any snapshot
- **feat**: Anti-compaction — frequent saves preserve full conversation content before Claude Code compresses it

### v1.4.0 — 2026-03-02

- **fix**: Use PowerShell syntax for Windows Terminal resume command (previously used CMD syntax)
- **fix**: Add `$LOCALAPPDATA` fallback when `wt` is not in PATH
- **feat**: Auto-detect terminal environment (VS Code, Windows Terminal, plain terminal) for resume
- **fix**: Clear `CLAUDECODE` env var before resume to prevent nested session errors

### v1.3.0 — 2026-03-02

- **docs**: Rewrite README — position Recall between Claude Code and OpenClaw
- **feat**: Improve save reliability and cross-project resume

### v1.2.0 — 2026-03-01

- **feat**: Add `/recall browse` interactive hierarchical navigation
- **feat**: Enhance `/recall list` with search, recent, and stats subcommands

### v1.0.0 — 2026-03-01

- **feat**: Initial release
- Cross-project session save, load, resume, rename, move
- Central session index with category-based organization
- Filesystem-first session detection

## License

MIT
