---
name: recall
description: |
  Cross-project session management hub for Claude Code. Use this skill when the user wants to
  manage conversations across different projects and directories.

  Trigger on /recall command or these specific phrases:
  - "/recall", "/recall save", "/recall list", "/recall load", "/recall resume", "/recall rename", "/recall move", "/recall manage", "/recall browse", "/recall history", "/recall search", "/recall context", "/recall notify", "/recall reindex"
  - "recall save", "recall list", "recall load", "recall resume", "recall rename", "recall move", "recall browse", "recall history", "recall search", "recall context", "recall notify", "recall reindex"
  - "recall 保存", "recall 列出", "recall 加载", "recall 恢复", "recall 重命名", "recall 移动", "recall 浏览", "recall 历史", "recall 搜索", "recall 上下文", "recall 通知"
  - "根据之前的讨论", "之前我们聊过", "之前的会话"

  Do NOT trigger on generic phrases like "save session" or "保存会话" alone — only when "recall" is explicitly mentioned or /recall is used.
  Exception: "根据之前的讨论", "之前我们聊过", "之前的会话" should trigger the /recall context command.
---

# Recall — Cross-Project Session Management Hub

Recall is a centralized session management system for Claude Code. It solves the problem that Claude Code isolates conversation history by project directory — you cannot see or resume sessions from other projects. Recall provides a central index with category-based organization.

## Architecture

**Central directory = Management index layer (mapping + categorization + version history)**

- The central directory (default: `D:\claude-sessions\`) stores metadata + backup copies of sessions
- Each session has a `_meta.json` (pointing to the original file) and a `.jsonl` backup
- Sessions are organized into user-defined categories (学习, 代码, 论文, etc.)
- Rename syncs bidirectionally: both the central index and the original project's sessions-index.json
- **Git versioning**: The central directory is a git repository. Every save/rename/move operation auto-commits, providing full version history for all sessions. This also serves as a safeguard against Claude Code's context compaction — frequent saves preserve complete conversation content even after compaction truncates the live session.

## Important Notes

- This skill is **independent** from Claude Code's built-in `/resume` and `/rename` commands
- Built-in `/resume` only shows current project sessions; Recall shows ALL projects
- `recall save` is a superset of `/rename`: it syncs the name to Claude's local sessions-index.json AND saves to central directory — using Recall makes `/rename` unnecessary
- Always use `AskUserQuestion` to confirm user intent before executing any operation
- All file paths must handle Windows paths correctly (backslashes, Chinese characters, spaces)

## Configuration

**Config file**: `{basePath}/_config.json`

```json
{
  "version": 1,
  "basePath": "D:\\claude-sessions",
  "categories": ["学习", "生活", "代码", "算法", "论文", "工作", "杂项"],
  "created": "2026-03-01T00:00:00Z"
}
```

**Meta file**: `{basePath}/{category}/{name}_meta.json`

```json
{
  "sessionId": "UUID",
  "name": "user-defined name",
  "category": "论文",
  "originalProject": "G:\\Research_20250121\\...",
  "originalProjectDir": "G--Research-20250121-12--...",
  "originalSessionFile": "C:\\Users\\ASUS\\.claude\\projects\\...\\uuid.jsonl",
  "backupFile": "D:\\claude-sessions\\论文\\name.jsonl",
  "created": "ISO 8601",
  "saved": "ISO 8601",
  "modified": "ISO 8601",
  "messageCount": 42,
  "firstPrompt": "first message preview...",
  "summary": "session summary",
  "tags": []
}
```

## Command Routing

Parse the ARGUMENTS value to determine which command to execute:

- No arguments or empty → **Entry Menu**
- `save` → **Save Session**
- `list` → **List Sessions** (supports sub-args: `search <keyword>`, `recent [N]`, `stats`)
- `load` → **Load Context**
- `resume` → **Resume Session**
- `rename` → **Rename Session**
- `move` → **Move Category**
- `manage` → **Manage Categories**
- `browse` → **Interactive Browse** (visual hierarchical navigation)
- `history` → **Version History** (view/compare/rollback git-versioned snapshots)
- `search <query>` → **Semantic Search** (embedding-based or keyword search)
- `context` → **Smart Context Injection** (auto-retrieve relevant history)
- `notify setup` → **Notification Setup** (configure WeChat notifications via Server酱)
- `reindex` → **Reindex All** (regenerate summaries + rebuild search index)

If ARGUMENTS doesn't match any command, treat it as a natural language query and infer the closest command, then confirm with the user.
If the user says "根据之前的讨论", "之前我们聊过", or "之前的会话", treat it as `/recall context`.

---

## Entry Menu (`/recall` with no arguments)

Use `AskUserQuestion` to present all available operations:

```
question: "Recall — 你想执行什么操作？"
options:
  - "save — 保存当前会话到中央目录"
  - "list — 列出所有已保存的会话"
  - "search — 语义搜索历史会话 (v2.0)"
  - "context — 智能记忆注入 (v2.0)"
  - "browse — 可视化交互浏览（类别→会话→操作）"
  - "history — 查看会话版本历史（对比/回滚）"
  - "load — 加载历史会话作为参考上下文"
  - "resume — 从中央目录恢复一个会话"
  - "rename — 重命名已保存的会话"
  - "move — 移动会话到其他类别"
  - "manage — 管理类别（增删、统计）"
  - "reindex — 重建所有会话的摘要和搜索索引 (v2.0)"
  - "notify setup — 配置微信通知 (v2.0)"
```

---

## Command 1: Save Session (`/recall save`)

### Workflow

1. **Initialize config** (if first run):
   - Check if `D:\claude-sessions\_config.json` exists
   - If not, use `AskUserQuestion` to ask user for the base path (default: `D:\claude-sessions`)
   - Create directory structure: base dir + all default category subdirs
   - Write `_config.json`

2. **Find current session** (filesystem-first approach):
   - Determine current working directory (use `pwd` via Bash)
   - Find the Claude projects directory for this project:
     - List `C:\Users\ASUS\.claude\projects\` directories
     - Match by checking which directory name corresponds to the current `pwd`
     - Path conversion rules: remove colon after drive letter, replace `\` or `/` with `--`, non-ASCII and special chars become dashes
     - If unsure, compare `projectPath` in `sessions-index.json` with current `pwd`
   - **Primary method — filesystem modification time** (reliable, works even when sessions-index.json is stale):
     - List all `*.jsonl` files in `C:\Users\ASUS\.claude\projects\{projectDir}\` sorted by modification time (newest first):
       ```bash
       ls -t "C:\Users\ASUS\.claude\projects\{projectDir}\"*.jsonl | head -1
       ```
     - The most recently modified `.jsonl` file IS the current session (it's being actively written to)
     - Extract sessionId from filename: e.g., `ed47c07e-9ecf-45e3-be1a-948d81d4a378.jsonl` → sessionId = `ed47c07e-9ecf-45e3-be1a-948d81d4a378`
   - **Get metadata** — try `sessions-index.json` first, fall back to `.jsonl` parsing:
     - Read `sessions-index.json` and look for the matching sessionId
     - If found: use its `summary`, `messageCount`, `firstPrompt`, `created`, `modified` fields
     - If NOT found (index is stale — this is common!): extract basic info from the `.jsonl` file:
       - `firstPrompt`: read first few lines of the `.jsonl`, find the first user message's content
       - `messageCount`: count lines with `wc -l` as rough estimate
       - `summary`: use firstPrompt as fallback summary (truncated to 50 chars)
       - `created`: use file creation time from filesystem
       - `modified`: use file modification time from filesystem

3. **Check if this session was previously saved** (auto-update detection):
   - Scan ALL `_meta.json` files across all categories in the central directory (use Glob: `{basePath}/**/*_meta.json`)
   - Look for any `_meta.json` where `sessionId` matches the current session's sessionId
   - **If found (previously saved)** → **Auto-update mode**:
     - Skip name/category selection — reuse existing name and category
     - Overwrite the `.jsonl` backup with the latest version: `cp` source → existing `backupFile` path
     - **Generate/update summary** (v2.0): run `python session_utils.py summarize "{backupFile}"` to get structured summary + tags, update `_meta.json` fields `summary` and `tags`
     - Update `_meta.json`: refresh `modified` timestamp, `messageCount`, `saved` timestamp, `summary`, `tags`
     - **Update search index** (v2.0): run `python recall_search.py index-one "{basePath}" "{sessionId}"` to refresh the embedding
     - **Git commit**: run `cd "{basePath}" && git add "{category}/{name}.jsonl" "{category}/{name}_meta.json" && git commit -m "update: {name} ({category}) - {messageCount}条消息"`
     - Report: "已自动更新备份: {name} ({category})"
     - **Done** — skip steps 4 and 5
   - **If not found (first save)** → continue to step 4

4. **Get user input** via `AskUserQuestion` (first save only):
   - **Session name**: Default to the `summary` field (from sessions-index if available, or firstPrompt fallback). Let user type a custom name via "Other" option.
   - **Category**: Show existing categories from `_config.json` + "新建类别" option

5. **Execute save** (first save only):
   - If user chose a new category: create the subdirectory and update `_config.json`
   - Copy the `.jsonl` file to `{basePath}/{category}/{name}.jsonl` using Bash `cp`
   - **Generate summary** (v2.0): run `python session_utils.py summarize "{basePath}/{category}/{name}.jsonl"` to get structured summary + tags
   - Create `{basePath}/{category}/{name}_meta.json` with all metadata (including `summary` and `tags` from the generated summary)
   - **Sync name back to Claude local storage**:
     - Read `sessions-index.json` and check if an entry with matching sessionId exists
     - If entry exists: update its `summary` field to the user-defined name
     - If entry does NOT exist (stale index): **add a new entry** to the entries array with all available fields (sessionId, fullPath, summary, messageCount, firstPrompt, created, modified, projectPath, etc.)
     - Write back `sessions-index.json`
   - **Git commit**: run `cd "{basePath}" && git add "{category}/{name}.jsonl" "{category}/{name}_meta.json" && git commit -m "add: {name} ({category}) - 新会话, {messageCount}条消息"`
   - Report success with the save location

### Key Details

- Sanitize the session name for use as filename (replace special chars)
- If a file with the same name already exists in that category but has a DIFFERENT sessionId, ask user whether to overwrite or use a different name
- Store the current timestamp as `saved`, preserve original `created` and `modified`
- **Auto-update**: When a session is saved again, the update is silent and fast — no user interaction needed

---

## Command 2: List Sessions (`/recall list`)

### Sub-argument Routing

Parse additional arguments after `list`:
- `list` (no sub-arg) → Default behavior (choose category → table with summary preview)
- `list --detail` → Detailed multi-line output per session (full summary + tags + project)
- `list search <keyword>` → Search across all sessions
- `list recent [N]` → Show most recent N sessions (default 10)
- `list stats` → Show statistics overview

### Workflow (default — no sub-arg)

1. Read `_config.json` to get basePath and categories
2. Use `AskUserQuestion` to let user choose:
   - A specific category to browse
   - Or "全部 — 所有类别" to see everything
3. Scan `_meta.json` files in the chosen category (or all categories) using Glob
4. Read each `_meta.json` and collect metadata
5. Display as a formatted table sorted by `modified` (newest first):

**Default mode** (摘要预览列替代来源项目):
```
#    名称                      类别     消息数  最后修改     摘要预览
1    ECCV论文202603             论文     4897   2026-03-03   论文写作: ECCV论文结构性修改...
2    Python调试                 代码     15     2026-02-27   问题修复: 帮我看一下这个bug...
```

**Detailed mode** (`--detail`, multi-line per session):
```
1    ECCV论文202603             论文     4897   2026-03-03
     论文写作: ECCV论文结构性修改——bib修复、Related Work同步。涉及 main.tex, references.bib
     标签: latex, 论文写作 | 来源: G:\Research...
```

6. After showing the table, ask user if they want to perform an action on any session (load, resume, rename, move)

Note: Summary quality depends on reindex. After upgrading to the new summary format, run `/recall reindex` to regenerate all summaries from the existing `.jsonl` backups.

### Workflow: Search (`/recall list search <keyword>`)

1. Run: `python session_utils.py search "{basePath}" "{keyword}"`
2. The script searches name, summary, firstPrompt, and tags fields (case-insensitive)
3. Display matching sessions as a table
4. If no matches found, tell the user and suggest trying different keywords

### Workflow: Recent (`/recall list recent [N]`)

1. Run: `python session_utils.py list "{basePath}" --sort modified --limit {N}`
2. Display the N most recently modified sessions across all categories
3. Default N=10 if not specified

### Workflow: Stats (`/recall list stats`)

1. Run: `python session_utils.py stats "{basePath}"`
2. Display statistics including:
   - Total session count and total message count
   - Per-category session counts
   - Most active category, largest session
   - Time range (earliest to latest save time)

---

## Command 3: Load Context (`/recall load`)

### Workflow

1. List sessions (same as list command, abbreviated)
2. Let user select one or more sessions to load
3. Ask user for extraction detail level:
   - **精简模式 (brief)**: Only user questions + assistant text answers
   - **详细模式 (detailed)**: Also includes tool names and key parameters (file paths, commands)
4. For each selected session, run the Python helper:
   ```bash
   python "C:\Users\ASUS\.claude\skills\recall\scripts\session_utils.py" extract "{backupFile}" --mode brief|detailed --max-messages 30
   ```
5. Present the extracted content clearly:
   ```
   --- 参考会话: {name} ({category}) ---
   [User] 首先 Expert Rubrics 两个词感觉有点冗余...
   [Assistant] 你说得对，我建议改为 Rule Learning...
   ...
   --- 参考会话结束 ---
   ```
6. Tell the user: "以上历史会话内容已加载为参考。你可以继续当前对话，我会参考这些上下文。"

---

## Command 4: Resume Session (`/recall resume`)

### Workflow

1. List sessions (same as list command)
2. User selects a session to resume
3. Read the session's `_meta.json` to get `sessionId`, `originalSessionFile`, and `originalProject`
4. Check if the original file still exists (use Bash `test -f`)
5. **If original is missing** (restore first):
   - Inform user the original was deleted but backup exists
   - Ask if they want to restore: copy backup `.jsonl` back to the original Claude projects directory
   - If yes:
     - Copy backup `.jsonl` to `C:\Users\ASUS\.claude\projects\{originalProjectDir}\{sessionId}.jsonl`
     - Update `sessions-index.json` in the target project directory (add entry if missing)
   - If no: abort
6. **Determine if same project or different project**:
   - Get current working directory via `pwd`
   - Compare with `originalProject` from `_meta.json`
   - **Same project**: just tell user to exit and run `claude --resume {sessionId}`
   - **Different project**: proceed to step 7
7. **Detect current terminal environment** (BEFORE showing options):
   - Run via Bash: `echo "TERM_PROGRAM=$TERM_PROGRAM WT_SESSION=$WT_SESSION VSCODE_INJECTION=$VSCODE_INJECTION"`
   - Detection rules:
     - **VSCode terminal**: `$TERM_PROGRAM == "vscode"` OR `$VSCODE_INJECTION == "1"`
     - **Windows Terminal**: `$WT_SESSION` is non-empty (has a UUID value)
     - **Standalone Git Bash**: `$MSYSTEM` is set but neither VSCode nor WT detected
     - **CMD/PowerShell**: none of the above
   - Store the detected environment for use in step 8

8. **Ask user for resume method** via `AskUserQuestion`:
   - Options vary based on detected environment (see below)
   - Always include "只显示命令" as the last option

   **If in VSCode terminal** → show these options:
   - **"VSCode 新窗口打开项目"** — Opens a new VSCode window at the target project
   - **"只显示命令"** — Show the command to copy

   **If in Windows Terminal** → show these options:
   - **"Windows Terminal 新标签页"** — Opens a new WT tab at the target project
   - **"VSCode 新窗口打开项目"** — Opens a new VSCode window
   - **"只显示命令"** — Show the command to copy

   **If in standalone Git Bash / CMD / other** → show these options:
   - **"VSCode 新窗口打开项目"** — Opens a new VSCode window
   - **"新终端窗口"** — Opens a new terminal window matching the current type
   - **"只显示命令"** — Show the command to copy

9. **Execute chosen method**:

   **Method: VSCode 新窗口打开项目**:
   - Run via Bash: `code "{originalProject}"`
   - This opens a NEW VSCode window at the target project
   - Display to user:
     ```
     已在 VSCode 中打开项目: {originalProject}

     请在新窗口的终端中执行：
     Remove-Item Env:CLAUDECODE -ErrorAction SilentlyContinue
     claude --resume {sessionId}
     ```

   **Method: Windows Terminal 新标签页**:
   - **IMPORTANT**: `wt` is often NOT in PATH when running inside Git Bash/MINGW64. Use the full path with fallback:
     ```bash
     wt.exe -w 0 new-tab -d "{originalProject}" 2>/dev/null || "$LOCALAPPDATA/Microsoft/WindowsApps/wt.exe" -w 0 new-tab -d "{originalProject}"
     ```
   - This opens a new tab in the CURRENT Windows Terminal window, already cd'd to the project
   - Display to user:
     ```
     已在 Windows Terminal 中打开新标签页，位于: {originalProject}

     请在新标签页中执行：
     Remove-Item Env:CLAUDECODE -ErrorAction SilentlyContinue; claude --resume {sessionId}
     ```
   - Note: `wt -w 0` targets the current WT window; `new-tab -d` sets the working directory
   - The new tab inherits the default profile (usually PowerShell). The command above uses PowerShell syntax.
   - If the user's default profile is CMD, use instead: `set CLAUDECODE= && claude --resume {sessionId}`
   - **Fallback path**: `$LOCALAPPDATA/Microsoft/WindowsApps/wt.exe` (standard install location for Windows Store apps)

   **Method: 新终端窗口** (standalone Git Bash):
   - Run via Bash: `start "" "C:\Program Files\Git\git-bash.exe" --cd="{originalProject}"`
   - Display to user:
     ```
     已打开新 Git Bash 窗口，位于: {originalProject}

     请在新窗口中执行：
     unset CLAUDECODE && claude --resume {sessionId}
     ```

   **Method: 只显示命令**:
   - Detect the user's shell from step 7 and show the appropriate command:
   - For **PowerShell** (VSCode default or Windows Terminal):
     ```
     会话: {name} ({category})
     项目: {originalProject}

     请在新终端中执行：
     cd "{originalProject}"
     Remove-Item Env:CLAUDECODE -ErrorAction SilentlyContinue
     claude --resume {sessionId}
     ```
   - For **Bash/Git Bash**:
     ```
     cd "{originalProject}" && unset CLAUDECODE && claude --resume {sessionId}
     ```
   - For **CMD**:
     ```
     cd /d "{originalProject}" && set CLAUDECODE= && claude --resume {sessionId}
     ```

### Notes

- **CRITICAL: Clear `CLAUDECODE` env var before resuming.** Terminals inherit environment variables from the parent process. If the parent had an active Claude Code session, the `CLAUDECODE` env var is set, causing "Error: Claude Code cannot be launched inside another Claude Code session". Always clear it first:
  - **PowerShell**: `Remove-Item Env:CLAUDECODE -ErrorAction SilentlyContinue`
  - **Bash/Git Bash**: `unset CLAUDECODE`
  - **CMD**: `set CLAUDECODE=`
- **Environment detection is key**: always detect first, then adapt options. Never hardcode Git Bash as the default terminal.
- The `code` command opens a new VSCode window — it does NOT affect the current window
- `wt -w 0 new-tab -d "{path}"` opens a tab in the current Windows Terminal window
- For Windows Terminal, the new tab inherits the default shell profile (PowerShell/CMD), so use the appropriate env var clearing syntax
- The user still needs to manually type the resume command in the new window/tab's terminal

---

## Command 5: Rename Session (`/recall rename`)

### Workflow

1. List sessions, user selects one to rename
2. Show current name, ask for new name via `AskUserQuestion`
3. **Bidirectional sync**:
   a. Update `_meta.json`: change `name` and `summary` fields
   b. Rename files in central directory:
      - `{old_name}_meta.json` → `{new_name}_meta.json`
      - `{old_name}.jsonl` → `{new_name}.jsonl`
      - Update `backupFile` path in meta
   c. Update original project's `sessions-index.json`:
      - Read the file at `C:\Users\ASUS\.claude\projects\{originalProjectDir}\sessions-index.json`
      - Find the entry matching `sessionId`
      - Update its `summary` field to the new name
      - Write back the file
   d. **Git commit**: run `cd "{basePath}" && git add -A && git commit -m "rename: {old_name} → {new_name} ({category})"`
4. Confirm success

---

## Command 6: Move Category (`/recall move`)

### Workflow

1. List sessions, user selects one to move
2. Show current category and available target categories (+ "新建类别" option)
3. If new category: create directory, update `_config.json`
4. Move files:
   ```bash
   mv "{basePath}/{oldCategory}/{name}_meta.json" "{basePath}/{newCategory}/{name}_meta.json"
   mv "{basePath}/{oldCategory}/{name}.jsonl" "{basePath}/{newCategory}/{name}.jsonl"
   ```
5. Update `_meta.json`: change `category` and `backupFile` fields
6. **Git commit**: run `cd "{basePath}" && git add -A && git commit -m "move: {name} 从 {oldCategory} → {newCategory}"`
7. Confirm success

---

## Command 7: Manage Categories (`/recall manage`)

### Workflow

1. Read `_config.json` and scan each category directory
2. Display category stats:
   ```
   | 类别 | 会话数 |
   |------|--------|
   | 学习 | 3 |
   | 代码 | 7 |
   | 论文 | 2 |
   | 生活 | 0 |
   ```
3. Ask user what they want to do:
   - **添加类别**: Enter new category name → create dir + update config
   - **删除空类别**: Only allow deleting categories with 0 sessions → remove dir + update config
   - **返回**: Go back

---

## Command 8: Interactive Browse (`/recall browse`)

A visual, hierarchical navigation interface using `AskUserQuestion` clickable options. Designed for managing large numbers of sessions (hundreds or thousands).

### Architecture: 3-Layer Navigation

```
Layer 1: Category Overview → Layer 2: Session List → Layer 3: Session Detail + Actions
```

### Layer 1 — Category Overview

1. Read `_config.json` + scan all category directories for `_meta.json` files
2. Count sessions per category, **filter out empty categories** (0 sessions)
3. For each non-empty category, find the most recently modified session as preview
4. Display using `AskUserQuestion`:
   - **question**: `"Recall 浏览 — 选择一个类别"`
   - **options**: Each non-empty category as an option
     - **label**: `"{类别名} ({N}个会话)"`
     - **description**: `"最近: {最新会话名} ({日期})"`
   - If non-empty categories > 3: use pagination
     - Show first 2 categories + "更多类别..." + "退出浏览"
     - "更多类别..." shows the next batch
   - If non-empty categories <= 3: show all + "退出浏览"
5. User selects a category → go to Layer 2

### Layer 2 — Session List (within a category)

1. Scan the selected category's `_meta.json` files, sort by `modified` descending
2. Display sessions using `AskUserQuestion`:
   - **question**: `"📂 {类别名} — {N}个会话 (第 {page}/{totalPages} 页)"`
   - **options**: Up to 3 sessions per page
     - **label**: Session name
     - **description**: `"{messageCount}条消息 | {modified日期} | {firstPrompt前30字}"`
   - Navigation options:
     - If more pages exist: include "下一页 →" option
     - Always include "← 返回类别列表" as last option
   - Pagination: 3 sessions per page. Page indicator in question text.
3. User selects a session → go to Layer 3
4. User selects "← 返回" → go back to Layer 1
5. User selects "下一页 →" → show next page of sessions

### Layer 3 — Session Detail + Actions

1. Read the selected session's `_meta.json` for full details
2. Display detail in the **question** text:
   ```
   📋 {name}
   ─────────────────
   类别: {category}
   消息数: {messageCount}
   来源项目: {originalProject}
   创建时间: {created}
   最后修改: {modified}
   摘要: {summary}
   首条消息: {firstPrompt前80字}
   标签: {tags}
   ```
3. **options** are executable actions:
   - **"load — 加载为参考上下文"**: Jump to Command 3 (Load Context) workflow with this session pre-selected
   - **"resume — 恢复此会话"**: Jump to Command 4 (Resume) workflow with this session pre-selected
   - **"rename / move — 重命名或移动"**: Ask user which one, then jump to Command 5 or 6
   - **"← 返回会话列表"**: Go back to Layer 2

### Implementation Notes

- The browse command is a **loop**: after each action completes, offer to return to browse
- All AskUserQuestion calls use `multiSelect: false` (single selection)
- Session data is read once at the start and cached for the browse session
- If the user types "Other" at any point, treat it as exit/cancel

---

## Command 9: Version History (`/recall history`)

View, compare, and rollback to any previous version of a saved session. Powered by git versioning of the central directory.

### Prerequisites

- The central directory (`{basePath}`) must be a git repository
- If not initialized: run `cd "{basePath}" && git init && git add -A && git commit -m "init: 初始化 Recall 中央目录"` first
- Git auto-commit is built into save/rename/move commands, so history accumulates automatically

### Workflow

1. **List sessions** (same as list command, abbreviated) and let user select one
2. **Get version history** for the selected session:
   ```bash
   cd "{basePath}" && git log --oneline --format="%h %ai %s" -- "{category}/{name}.jsonl"
   ```
   This returns all commits that touched this session's `.jsonl` file.
3. **Parse and display** the version list via `AskUserQuestion`:
   - **question**: Include a formatted version table:
     ```
     📜 {name} — 版本历史 ({N}个版本)
     ─────────────────
     | # | 版本 | 时间 | 说明 |
     |---|------|------|------|
     | 1 | a3f2b1c | 2026-03-03 17:45 | update: ECCV论文 - 4897条消息 (当前) |
     | 2 | d8e4f5a | 2026-03-02 20:00 | update: ECCV论文 - 3200条消息 |
     | 3 | 7c3e8a1 | 2026-03-02 13:00 | add: ECCV论文 - 新会话 |
     ```
   - **options**:
     - **"对比两个版本"** — Compare two versions side by side
     - **"回滚到某个版本"** — Restore a historical version as current
     - **"仅查看"** — Just view the history, no action
4. **Execute chosen action**:

### Action: 对比两个版本

1. Ask user to select two version numbers (e.g., "1 和 3" or "最新 和 上一个")
   - Use `AskUserQuestion` with options like: "最新 vs 上一个", "选择两个版本号 (Other)"
2. Extract both versions to temp files:
   ```bash
   cd "{basePath}" && git show {older_hash}:"{category}/{name}.jsonl" > /tmp/recall_diff_old.jsonl
   cd "{basePath}" && git show {newer_hash}:"{category}/{name}.jsonl" > /tmp/recall_diff_new.jsonl
   ```
3. Run the diff command via the Python helper:
   ```bash
   python "C:\Users\ASUS\.claude\skills\recall\scripts\session_utils.py" diff /tmp/recall_diff_old.jsonl /tmp/recall_diff_new.jsonl --mode brief|detailed --max-messages 50
   ```
4. The script uses message UUID matching to identify:
   - **新增记录**: Messages in the newer version but not the older (= incremental conversation)
   - **被压缩记录**: Messages in the older version but not the newer (= lost to compaction)
   - **Compaction detection**: Automatically detects `summary`/`compact_boundary` markers
5. Display the script's output, which includes:
   ```
   === 版本差异分析 ===
   旧版本: 1500 条记录 ({older_date})
   新版本: 3200 条记录 ({newer_date})
   新增:   1700 条记录
   移除:   0 条记录

   --- 新增对话内容 ---
   [User] 帮我看一下这个bug...
   [Assistant] 我来检查一下代码...
   ...
   ```
   If compaction is detected:
   ```
   ⚠ 检测到 compact（上下文压缩）: 部分早期消息已被摘要替代

   --- 被 compact 压缩的早期对话 ---
   [User] 最早的一些对话内容...
   [Assistant] 这些内容在新版本中已被压缩...
   ```
6. After displaying diff, ask if user wants to:
   - Load either version's full content as context
   - Rollback to the older version

### Action: 回滚到某个版本

1. Ask user which version to rollback to (show version list as options)
2. **Confirm with user**: "确认要将 {name} 回滚到版本 {hash} ({date})？当前版本不会丢失，可以随时恢复。"
3. Execute rollback:
   ```bash
   cd "{basePath}" && git checkout {target_hash} -- "{category}/{name}.jsonl" "{category}/{name}_meta.json"
   ```
4. **Auto-commit the rollback** so it's tracked in history:
   ```bash
   cd "{basePath}" && git add "{category}/{name}.jsonl" "{category}/{name}_meta.json" && git commit -m "rollback: {name} ({category}) → 版本 {target_hash}"
   ```
5. Report success:
   ```
   已回滚 {name} 到版本 {target_hash} ({date})
   原版本仍在 git 历史中，可随时通过 /recall history 恢复。
   ```

### Action: 加载历史版本内容

This is an extension of the Load Context command (Command 3) that loads a specific historical version instead of the current one.

1. User selects a version from the history list
2. Extract the historical `.jsonl` to a temp file:
   ```bash
   cd "{basePath}" && git show {target_hash}:"{category}/{name}.jsonl" > /tmp/recall_history_temp.jsonl
   ```
3. Run the session_utils.py extract command on the temp file (same as Command 3)
4. Present the content with a version indicator:
   ```
   --- 参考会话: {name} (版本 {hash}, {date}) ---
   [User] ...
   [Assistant] ...
   --- 参考会话结束 ---
   ```

### Notes

- All versions are permanent — rollback creates a new commit, never deletes history
- If git is not initialized in basePath, tell the user and offer to initialize it
- The `_meta.json` is also versioned, so messageCount/timestamps are accurate per version
- For sessions with many versions (>10), paginate the version list (show 10 per page)

---

## Command 10: Semantic Search (`/recall search <query>`) — v2.0

Embedding-based or keyword search across all saved sessions.

### Workflow

1. Read `_config.json` to get basePath
2. Run the semantic search script:
   ```bash
   python "C:\Users\ASUS\.claude\skills\recall\scripts\recall_search.py" search "{basePath}" "{query}" --top-k 5
   ```
3. The script automatically chooses:
   - **Semantic search** (if OpenAI API key is configured): embeds the query, computes cosine similarity against all session embeddings
   - **Keyword search** (fallback): scores sessions by keyword matches in name, summary, tags, firstPrompt
4. Display results as a table with similarity/relevance score
5. After showing results, ask user if they want to:
   - **Load** one of the matching sessions as context
   - **Open** the session detail (jump to browse Layer 3)

### First-time Setup

If the search index (`{basePath}/_index.sqlite`) doesn't exist yet, tell the user:
- "搜索索引尚未创建。正在为所有已保存会话建立索引..."
- Run: `python recall_search.py index "{basePath}"`
- Then proceed with the search

### Embedding Configuration

For semantic search (optional but recommended), the user needs an OpenAI API key:
- Set via environment: `export OPENAI_API_KEY=sk-xxx`
- Or add to `_config.json`: `"openai_api_key": "sk-xxx"`
- Without an API key, the system falls back to keyword search (still useful!)

---

## Command 11: Smart Context Injection (`/recall context`) — v2.0

Automatically retrieves and injects relevant historical session summaries based on the current conversation topic.

### Trigger Phrases

- `/recall context`
- "根据之前的讨论" (automatically detected)
- "之前我们聊过" (automatically detected)
- "之前的会话" (automatically detected)

### Workflow

1. **Extract current topic**: Analyze the most recent 3-5 user messages in the current conversation to identify key topics/keywords
2. **Search for related sessions**: Run the semantic search:
   ```bash
   python "C:\Users\ASUS\.claude\skills\recall\scripts\recall_search.py" search "{basePath}" "{extracted_topic}" --top-k 3
   ```
3. **Parse results**: Extract the JSON results from the script output (after "--- JSON ---" marker)
4. **Load summaries**: For each matched session, read its `_meta.json` to get the `summary` field
5. **Display injected context**:
   ```
   --- 相关历史上下文 (自动检索) ---
   [会话: {name1}] ({category1}, {date1}) {summary1}
   [会话: {name2}] ({category2}, {date2}) {summary2}
   [会话: {name3}] ({category3}, {date3}) {summary3}
   --- 上下文结束 (如需完整内容请用 /recall load) ---
   ```
6. Continue the conversation with this context available

### Key Design Principles

- Total injected token budget: ~600 tokens (3 sessions × ~200 tokens each)
- Only inject **summaries**, never full conversation content (that's what `/recall load` is for)
- If no related sessions found, say: "未找到与当前主题相关的历史会话。"
- If search index doesn't exist, suggest running `/recall reindex` first

---

## Command 12: Notification Setup (`/recall notify setup`) — v2.0

Configure WeChat notifications via Server酱 (ServerChan) for task completion alerts.

### Workflow

1. Read current `_config.json` to check existing notify configuration
2. Use `AskUserQuestion` to guide setup:
   ```
   question: "Recall 微信通知配置"
   options:
     - "配置 Server酱 SENDKEY"
     - "测试通知"
     - "启用/禁用通知"
     - "查看当前配置"
   ```

3. **配置 SENDKEY**:
   - Tell user: "请前往 https://sct.ftqq.com/ 注册并获取 SENDKEY"
   - Ask user to input their SENDKEY (via AskUserQuestion "Other" option)
   - Update `_config.json`:
     ```json
     {
       "notify": {
         "provider": "serverchan",
         "sendkey": "SCTxxx",
         "enabled": true
       }
     }
     ```
   - Git commit the config change

4. **测试通知**:
   - Run: `echo '{"task_subject": "测试通知", "status": "completed", "cwd": "'$(pwd)'"}' | python "C:\Users\ASUS\.claude\skills\recall\scripts\recall_notify.py"`
   - Tell user to check their WeChat for the test notification

5. **启用/禁用**:
   - Toggle `notify.enabled` in `_config.json`

### Notes

- Server酱 is completely free for basic usage (up to 5 messages/day on free tier)
- The `TaskCompleted` hook is registered in `~/.claude/settings.json` — it fires when any task in Claude Code's task list is marked as completed
- Notifications include: task title, completion status, project path

---

## Command 13: Reindex All Sessions (`/recall reindex`) — v2.0

Regenerate summaries and rebuild the search index for all saved sessions. Essential for:
- Existing sessions saved before v2.0 (which have empty summary/tags)
- After upgrading to v2.0
- Periodic index refresh

### Workflow

1. Read `_config.json` to get basePath and categories
2. **Phase 1: Regenerate summaries** for sessions that need it:
   - For each `_meta.json` in all categories:
     - Read existing `summary` and `tags` from `_meta.json`
     - **Skip if existing summary is good**: If `summary` is non-empty AND >= 30 characters, **preserve it** and skip to the next session. Report: "跳过 (已有摘要): {name}"
     - Only for sessions with empty/short summary: Find the corresponding `.jsonl` backup file
     - Run: `python session_utils.py summarize "{backupFile}"`
     - Parse the JSON output (summary + tags)
     - Update `_meta.json` with the new `summary` and `tags` fields
     - Report progress: "正在处理: {name} ({category})..."
   - **Force mode**: If the user explicitly says "强制重建" or passes `--force`, overwrite ALL summaries regardless of existing content
3. **Phase 2: Rebuild search index**:
   - Run: `python recall_search.py index "{basePath}"`
   - This creates/updates `_index.sqlite` with all session data and embeddings
4. **Git commit**: `cd "{basePath}" && git add -A && git commit -m "reindex: 重建所有会话摘要和搜索索引"`
5. Report:
   ```
   Reindex 完成:
   - {N} 个会话已更新摘要
   - 搜索索引已重建 ({M} 条记录)
   - Embedding: {OpenAI/未配置}
   ```

### Notes

- This can take a while for large collections (each session needs JSONL parsing)
- If OpenAI API key is configured, each session also gets an embedding (~$0.02/百万token, almost free)
- Without API key, only keyword search will work (still useful)
- Safe to run multiple times — search index is always rebuilt, but existing good summaries are preserved (unless `--force`)
- **Important**: Auto-generated summaries from compacted sessions may be worse than manually written ones. The skip logic protects against this regression.

---

## Helper Script Reference

The Python helper script is located at:
`C:\Users\ASUS\.claude\skills\recall\scripts\session_utils.py`

### Usage

```bash
# Extract readable content from a session
python session_utils.py extract <jsonl_path> [--mode brief|detailed] [--max-messages 30] [--max-chars 500]

# List all sessions in the central directory (default: summary preview column)
python session_utils.py list <base_dir> [--category <name>] [--sort modified|name|count] [--limit N] [--detail]

# Search sessions by keyword
python session_utils.py search <base_dir> <keyword> [--category <name>]

# Show statistics overview
python session_utils.py stats <base_dir>

# Check if original session files still exist
python session_utils.py check <base_dir>

# Compare two versions of a session (extract incremental content + detect compaction)
python session_utils.py diff <old_jsonl_path> <new_jsonl_path> [--mode brief|detailed] [--max-messages 50] [--max-chars 500]

# Generate structured summary and tags from a session (v2.0)
python session_utils.py summarize <jsonl_path> [--max-chars 300]
# Output: JSON {"summary": "...", "tags": ["..."]}
```

### Semantic Search Script (v2.0)

Located at: `C:\Users\ASUS\.claude\skills\recall\scripts\recall_search.py`

```bash
# Index all sessions (build/rebuild search database)
python recall_search.py index <base_dir>

# Index a single session (after save/update)
python recall_search.py index-one <base_dir> <session_id>

# Semantic search (uses embeddings if available, falls back to keyword)
python recall_search.py search <base_dir> <query> [--top-k 5]

# Keyword-only search
python recall_search.py keyword <base_dir> <query>
```

### Auto-Save Script (v2.0)

Located at: `C:\Users\ASUS\.claude\skills\recall\scripts\recall_autosave.py`
- Triggered by `SessionEnd` hook
- Reads JSON from stdin, updates previously-saved sessions only
- Silently skips if session was never saved via `/recall save`

### Notification Script (v2.0)

Located at: `C:\Users\ASUS\.claude\skills\recall\scripts\recall_notify.py`
- Triggered by `TaskCompleted` hook
- Sends WeChat notification via Server酱 API
- Configured via `_config.json` `notify` field

### When to use the helper vs. direct tools

- **Use helper for**: Extracting session content, generating summaries, semantic search (parsing large JSONL efficiently)
- **Use direct tools for**: Reading/writing meta.json, copying files, reading config (simpler operations)

---

## Path Conversion Reference

To convert a project path to its Claude projects directory name:

```
Input:  G:\Research_20250121\12建筑尺度城市分析和模拟（aum+bs）\投稿\building simulation
Output: G--Research-20250121-12------------aum-bs-----building-simulation
```

Rules:
1. Remove the colon after drive letter
2. Replace `\` and `/` with `--`
3. Non-ASCII characters and special chars are converted (parentheses, plus, spaces become dashes)

The safest approach: use Bash to `ls` the `C:\Users\ASUS\.claude\projects\` directory and find the matching project dir by checking which one's `sessions-index.json` contains `projectPath` matching the current `pwd`.
