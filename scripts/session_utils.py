#!/usr/bin/env python3
"""
Recall Session Utils — Helper script for cross-project session management.

Subcommands:
  extract  - Extract readable content from a session .jsonl file
  list     - List all saved sessions in the central directory
  check    - Verify that original session files still exist
"""

import argparse
import json
import os
import platform
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows terminal encoding for Chinese characters
if platform.system() == "Windows" or "MSYS" in os.environ.get("MSYSTEM", ""):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _normalize_path(path_str: str) -> str:
    """Convert MSYS-style paths (/c/Users/...) to Windows paths (C:\\Users\\...) if needed."""
    if len(path_str) >= 3 and path_str[0] == "/" and path_str[2] == "/":
        drive_letter = path_str[1].upper()
        return f"{drive_letter}:{path_str[2:]}".replace("/", "\\")
    return path_str


def _safe_load_json(file_path) -> dict:
    """Load JSON file with fallback to fix unescaped Windows backslashes.

    Claude Code and SKILL.md sometimes write paths like C:\\Users instead of C:\\\\Users
    in JSON files, which is invalid JSON. This function handles that gracefully.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fix unescaped backslashes: match \ not preceded by \ and not followed by valid escape char
        fixed = re.sub(r'(?<!\\)\\(?![\\"/bfnrtu])', r'\\\\', raw)
        return json.loads(fixed)


def extract_session(jsonl_path: str, mode: str = "brief", max_messages: int = 30, max_chars: int = 500) -> str:
    """Extract readable conversation content from a session .jsonl file.

    Args:
        jsonl_path: Path to the .jsonl session file
        mode: 'brief' (user + assistant text only) or 'detailed' (includes tool info)
        max_messages: Maximum number of messages to extract
        max_chars: Maximum characters per message
    """
    path = Path(_normalize_path(jsonl_path))
    if not path.exists():
        return f"Error: File not found: {jsonl_path}"

    messages = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "")
                msg = entry.get("message", {})

                if entry_type == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        text = content.strip()
                        # Skip tool_result entries (they appear as user messages)
                        if not text.startswith("{") and "tool_use_id" not in text:
                            messages.append(("User", _truncate(text, max_chars)))
                    elif isinstance(content, list):
                        # Extract text parts, skip tool_result parts
                        text_parts = []
                        for part in content:
                            if isinstance(part, dict):
                                if part.get("type") == "text":
                                    text_parts.append(part.get("text", ""))
                                elif part.get("type") == "tool_result" and mode == "detailed":
                                    # In detailed mode, show a brief note about tool results
                                    tool_content = part.get("content", "")
                                    if isinstance(tool_content, str) and len(tool_content) > 0:
                                        preview = _truncate(tool_content, 100)
                                        text_parts.append(f"[Tool Result: {preview}]")
                        combined = "\n".join(text_parts).strip()
                        if combined:
                            messages.append(("User", _truncate(combined, max_chars)))

                elif entry_type == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        messages.append(("Assistant", _truncate(content.strip(), max_chars)))
                    elif isinstance(content, list):
                        text_parts = []
                        tool_notes = []
                        for part in content:
                            if isinstance(part, dict):
                                if part.get("type") == "text":
                                    text_parts.append(part.get("text", ""))
                                elif part.get("type") == "tool_use" and mode == "detailed":
                                    tool_name = part.get("name", "unknown")
                                    tool_input = part.get("input", {})
                                    # Extract key info based on tool type
                                    note = _summarize_tool_use(tool_name, tool_input)
                                    if note:
                                        tool_notes.append(note)
                                # Skip 'thinking' blocks entirely
                        combined = "\n".join(text_parts).strip()
                        if tool_notes:
                            combined += "\n" + "\n".join(f"  [{note}]" for note in tool_notes)
                        if combined:
                            messages.append(("Assistant", _truncate(combined, max_chars)))

    except Exception as e:
        return f"Error reading file: {e}"

    if not messages:
        return "No readable messages found in session."

    # Limit to max_messages
    if len(messages) > max_messages:
        messages = messages[:max_messages]

    # Format output
    output_lines = []
    for role, text in messages:
        output_lines.append(f"[{role}] {text}")
        output_lines.append("")  # blank line between messages

    return "\n".join(output_lines)


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, adding ellipsis if needed."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _summarize_tool_use(tool_name: str, tool_input: dict) -> str:
    """Create a brief summary of a tool use for detailed mode."""
    if tool_name in ("Read", "Glob", "Grep"):
        path = tool_input.get("file_path", "") or tool_input.get("path", "") or tool_input.get("pattern", "")
        return f"Tool: {tool_name} → {path}" if path else f"Tool: {tool_name}"
    elif tool_name == "Edit":
        path = tool_input.get("file_path", "")
        return f"Tool: Edit → {path}" if path else "Tool: Edit"
    elif tool_name == "Write":
        path = tool_input.get("file_path", "")
        return f"Tool: Write → {path}" if path else "Tool: Write"
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if cmd:
            return f"Tool: Bash → {_truncate(cmd, 80)}"
        return "Tool: Bash"
    elif tool_name == "Agent":
        desc = tool_input.get("description", "")
        return f"Tool: Agent → {desc}" if desc else "Tool: Agent"
    else:
        return f"Tool: {tool_name}"


def _load_all_sessions(base_path: Path, category: str = None) -> list:
    """Load all session metadata from the central directory.

    Args:
        base_path: Path object for central sessions directory
        category: Optional category filter
    Returns:
        List of session metadata dicts
    """
    config_path = base_path / "_config.json"
    if not config_path.exists():
        return []

    try:
        config = _safe_load_json(config_path)
    except Exception:
        return []

    categories = [category] if category else config.get("categories", [])
    sessions = []

    for cat in categories:
        cat_dir = base_path / cat
        if not cat_dir.exists():
            continue
        for meta_file in cat_dir.glob("*_meta.json"):
            try:
                meta = _safe_load_json(meta_file)
                sessions.append(meta)
            except Exception:
                continue

    return sessions


def list_sessions(base_dir: str, category: str = None, sort_by: str = "modified",
                   limit: int = 0, detail: bool = False) -> str:
    """List all saved sessions in the central directory.

    Args:
        base_dir: Path to the central sessions directory
        category: Optional category filter
        sort_by: Sort key — 'modified' (default), 'name', or 'count'
        limit: Maximum number of sessions to show (0 = unlimited)
        detail: If True, show multi-line detail per session (full summary + tags + project)
    """
    base_path = Path(_normalize_path(base_dir))
    if not base_path.exists():
        return f"Error: Directory not found: {base_dir}"

    sessions = _load_all_sessions(base_path, category)

    if not sessions:
        if category:
            return f"No sessions found in category: {category}"
        return "No sessions saved yet."

    # Sort
    if sort_by == "name":
        sessions.sort(key=lambda s: s.get("name", "").lower())
    elif sort_by == "count":
        sessions.sort(key=lambda s: s.get("messageCount", 0), reverse=True)
    else:  # modified (default)
        sessions.sort(key=lambda s: s.get("modified", ""), reverse=True)

    # Limit
    if limit > 0:
        sessions = sessions[:limit]

    lines = []

    if detail:
        # Detailed mode: multi-line per session
        lines.append(f"{'#':<4} {'名称':<25} {'类别':<8} {'消息数':<6} {'最后修改':<12}")
        lines.append("-" * 60)

        for i, s in enumerate(sessions, 1):
            name = _truncate(s.get("name", "unnamed"), 24)
            cat = s.get("category", "?")
            count = s.get("messageCount", "?")
            modified = s.get("modified", "?")
            if isinstance(modified, str) and len(modified) >= 10:
                modified = modified[:10]
            lines.append(f"{i:<4} {name:<25} {cat:<8} {str(count):<6} {modified:<12}")
            # Summary line
            summary = s.get("summary", "")
            if summary:
                lines.append(f"     {summary}")
            # Tags + project line
            tags = s.get("tags", [])
            project = s.get("originalProject", "?")
            if len(project) > 40:
                project = "..." + project[-37:]
            tag_str = ", ".join(tags) if tags else ""
            if tag_str and project:
                lines.append(f"     标签: {tag_str} | 来源: {project}")
            elif project:
                lines.append(f"     来源: {project}")
            lines.append("")  # blank line between sessions
    else:
        # Default mode: summary preview replaces project column
        lines.append(f"{'#':<4} {'名称':<25} {'类别':<8} {'消息数':<6} {'最后修改':<12} {'摘要预览':<30}")
        lines.append("-" * 90)

        for i, s in enumerate(sessions, 1):
            name = _truncate(s.get("name", "unnamed"), 24)
            cat = s.get("category", "?")
            count = s.get("messageCount", "?")
            modified = s.get("modified", "?")
            if isinstance(modified, str) and len(modified) >= 10:
                modified = modified[:10]
            summary = s.get("summary", "")
            preview = _truncate(summary, 30) if summary else "-"
            lines.append(f"{i:<4} {name:<25} {cat:<8} {str(count):<6} {modified:<12} {preview:<30}")

    total_info = f"\n共 {len(sessions)} 个会话"
    if limit > 0:
        total_info += f" (显示前 {limit} 个)"
    lines.append(total_info)

    return "\n".join(lines)


def search_sessions(base_dir: str, keyword: str, category: str = None) -> str:
    """Search sessions by keyword across name, summary, firstPrompt, and tags.

    Args:
        base_dir: Path to the central sessions directory
        keyword: Search keyword (case-insensitive)
        category: Optional category filter
    """
    base_path = Path(_normalize_path(base_dir))
    if not base_path.exists():
        return f"Error: Directory not found: {base_dir}"

    sessions = _load_all_sessions(base_path, category)
    if not sessions:
        return "No sessions saved yet."

    keyword_lower = keyword.lower()
    matches = []

    for s in sessions:
        searchable = " ".join([
            s.get("name", ""),
            s.get("summary", ""),
            s.get("firstPrompt", ""),
            " ".join(s.get("tags", [])),
        ]).lower()
        if keyword_lower in searchable:
            matches.append(s)

    if not matches:
        return f"No sessions matching '{keyword}'."

    # Sort by modified (newest first)
    matches.sort(key=lambda s: s.get("modified", ""), reverse=True)

    lines = []
    lines.append(f"搜索 '{keyword}' — 找到 {len(matches)} 个匹配:")
    lines.append("")
    lines.append(f"{'#':<4} {'名称':<25} {'类别':<8} {'消息数':<6} {'最后修改':<12} {'摘要预览':<30}")
    lines.append("-" * 90)

    for i, s in enumerate(matches, 1):
        name = _truncate(s.get("name", "unnamed"), 24)
        cat = s.get("category", "?")
        count = s.get("messageCount", "?")
        modified = s.get("modified", "?")
        if isinstance(modified, str) and len(modified) >= 10:
            modified = modified[:10]
        summary = s.get("summary", "")
        preview = _truncate(summary, 30) if summary else "-"
        lines.append(f"{i:<4} {name:<25} {cat:<8} {str(count):<6} {modified:<12} {preview:<30}")

    return "\n".join(lines)


def stats_sessions(base_dir: str) -> str:
    """Show statistics overview of all saved sessions.

    Args:
        base_dir: Path to the central sessions directory
    """
    base_path = Path(_normalize_path(base_dir))
    if not base_path.exists():
        return f"Error: Directory not found: {base_dir}"

    config_path = base_path / "_config.json"
    if not config_path.exists():
        return "Error: _config.json not found."

    try:
        config = _safe_load_json(config_path)
    except Exception as e:
        return f"Error reading config: {e}"

    categories = config.get("categories", [])
    cat_counts = {}
    all_sessions = []

    for cat in categories:
        cat_dir = base_path / cat
        if not cat_dir.exists():
            cat_counts[cat] = 0
            continue
        count = 0
        for meta_file in cat_dir.glob("*_meta.json"):
            try:
                meta = _safe_load_json(meta_file)
                all_sessions.append(meta)
                count += 1
            except Exception:
                continue
        cat_counts[cat] = count

    total_sessions = len(all_sessions)
    total_messages = sum(s.get("messageCount", 0) for s in all_sessions)

    lines = []
    lines.append("=== Recall 统计概览 ===")
    lines.append("")
    lines.append(f"总会话数: {total_sessions}")
    lines.append(f"总消息数: {total_messages}")
    lines.append(f"类别数:   {len(categories)}")
    lines.append("")

    # Per-category table
    lines.append(f"{'类别':<10} {'会话数':<8} {'消息数':<10}")
    lines.append("-" * 30)
    for cat in categories:
        count = cat_counts.get(cat, 0)
        cat_messages = sum(
            s.get("messageCount", 0) for s in all_sessions if s.get("category") == cat
        )
        lines.append(f"{cat:<10} {count:<8} {cat_messages:<10}")

    if all_sessions:
        lines.append("")
        # Most active category
        most_active = max(cat_counts, key=cat_counts.get)
        lines.append(f"最活跃类别: {most_active} ({cat_counts[most_active]} 个会话)")

        # Largest session
        largest = max(all_sessions, key=lambda s: s.get("messageCount", 0))
        lines.append(f"最大会话:   {largest.get('name', '?')} ({largest.get('messageCount', 0)} 条消息)")

        # Time range
        saved_times = [s.get("saved", "") for s in all_sessions if s.get("saved")]
        if saved_times:
            earliest = min(saved_times)[:10]
            latest = max(saved_times)[:10]
            lines.append(f"时间范围:   {earliest} ~ {latest}")

    return "\n".join(lines)


def check_sessions(base_dir: str) -> str:
    """Check if original session files still exist for all saved sessions.

    Args:
        base_dir: Path to the central sessions directory
    """
    base_path = Path(_normalize_path(base_dir))
    if not base_path.exists():
        return f"Error: Directory not found: {base_dir}"

    config_path = base_path / "_config.json"
    if not config_path.exists():
        return "Error: _config.json not found."

    try:
        config = _safe_load_json(config_path)
    except Exception as e:
        return f"Error reading config: {e}"

    categories = config.get("categories", [])
    results = {"ok": [], "missing": [], "error": []}

    for cat in categories:
        cat_dir = base_path / cat
        if not cat_dir.exists():
            continue
        for meta_file in cat_dir.glob("*_meta.json"):
            try:
                meta = _safe_load_json(meta_file)
                name = meta.get("name", "unnamed")
                original = meta.get("originalSessionFile", "")
                if original and Path(original).exists():
                    results["ok"].append(f"  OK: {name} ({cat}) → {original}")
                else:
                    results["missing"].append(f"  MISSING: {name} ({cat}) → {original}")
            except Exception as e:
                results["error"].append(f"  ERROR: {meta_file.name} → {e}")

    lines = []
    total = len(results["ok"]) + len(results["missing"]) + len(results["error"])
    lines.append(f"Checked {total} sessions:")
    lines.append(f"  ✓ {len(results['ok'])} OK")
    lines.append(f"  ✗ {len(results['missing'])} missing original")
    lines.append(f"  ! {len(results['error'])} errors")

    if results["missing"]:
        lines.append("\nMissing originals (backup copies still available):")
        lines.extend(results["missing"])

    if results["error"]:
        lines.append("\nErrors:")
        lines.extend(results["error"])

    return "\n".join(lines)


def _parse_jsonl_entries(path: Path) -> list:
    """Parse a .jsonl file and return list of (line_number, entry_dict) tuples."""
    entries = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entries.append((i, entry))
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return entries


def _entry_id(entry: dict) -> str:
    """Extract a unique identifier for a jsonl entry.

    Priority: uuid > message.id > hash of content.
    """
    if entry.get("uuid"):
        return entry["uuid"]
    msg = entry.get("message", {})
    if isinstance(msg, dict) and msg.get("id"):
        return msg["id"]
    # Fallback: hash the entry type + first 200 chars of content
    entry_type = entry.get("type", "")
    content = str(entry.get("message", {}).get("content", ""))[:200]
    return f"{entry_type}:{hash(content)}"


def _is_compact_marker(entry: dict) -> bool:
    """Check if an entry is a compaction boundary marker."""
    return entry.get("type") == "summary" or "compact_boundary" in str(entry)


def _extract_readable(entries: list, mode: str = "brief", max_chars: int = 500) -> list:
    """Convert parsed entries to readable (role, text) tuples.

    Args:
        entries: list of (line_number, entry_dict) tuples
        mode: 'brief' or 'detailed'
        max_chars: max chars per message
    Returns:
        list of (role, text) tuples
    """
    messages = []
    for _, entry in entries:
        entry_type = entry.get("type", "")
        msg = entry.get("message", {})

        if entry_type == "user":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                text = content.strip()
                if not text.startswith("{") and "tool_use_id" not in text:
                    messages.append(("User", _truncate(text, max_chars)))
            elif isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                combined = "\n".join(text_parts).strip()
                if combined:
                    messages.append(("User", _truncate(combined, max_chars)))

        elif entry_type == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                messages.append(("Assistant", _truncate(content.strip(), max_chars)))
            elif isinstance(content, list):
                text_parts = []
                tool_notes = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "tool_use" and mode == "detailed":
                            note = _summarize_tool_use(part.get("name", ""), part.get("input", {}))
                            if note:
                                tool_notes.append(note)
                combined = "\n".join(text_parts).strip()
                if tool_notes:
                    combined += "\n" + "\n".join(f"  [{note}]" for note in tool_notes)
                if combined:
                    messages.append(("Assistant", _truncate(combined, max_chars)))

        elif entry_type == "summary":
            summary_text = msg.get("content", "") if isinstance(msg, dict) else str(msg)
            if isinstance(summary_text, str) and summary_text.strip():
                messages.append(("System/Compact", _truncate(summary_text.strip(), max_chars)))

    return messages


def _extract_session_data(entries: list) -> dict:
    """Extract structured data (user messages, tool uses, files) from parsed entries.

    Returns dict with keys: user_messages, assistant_messages, tool_uses, file_counts
    """
    user_messages = []
    assistant_messages = []
    tool_uses = []
    file_counts = Counter()

    for _, entry in entries:
        entry_type = entry.get("type", "")
        msg = entry.get("message", {})
        content = msg.get("content", "") if isinstance(msg, dict) else ""

        if entry_type == "user":
            text = ""
            if isinstance(content, str):
                text = content.strip()
            elif isinstance(content, list):
                text_parts = [p.get("text", "") for p in content
                              if isinstance(p, dict) and p.get("type") == "text"]
                text = " ".join(text_parts).strip()
            if text and not text.startswith("{") and "tool_use_id" not in text:
                user_messages.append(text)

        elif entry_type == "assistant":
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        assistant_messages.append(part.get("text", "").strip())
                    elif part.get("type") == "tool_use":
                        tool_name = part.get("name", "")
                        tool_input = part.get("input", {})
                        tool_uses.append(tool_name)
                        # Extract file paths from tool inputs
                        for key in ("file_path", "path", "pattern"):
                            val = tool_input.get(key, "")
                            if val and isinstance(val, str) and ("/" in val or "\\" in val):
                                fname = val.replace("\\", "/").split("/")[-1]
                                if "." in fname and len(fname) < 80:
                                    file_counts[fname] += 1
                        # Extract from bash commands
                        if tool_name == "Bash":
                            cmd = tool_input.get("command", "")
                            for m in re.findall(r'[\w./\\-]+\.\w{1,5}', cmd):
                                fname = m.replace("\\", "/").split("/")[-1]
                                if len(fname) < 80:
                                    file_counts[fname] += 1
            elif isinstance(content, str) and content.strip():
                assistant_messages.append(content.strip())

    return {
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "tool_uses": tool_uses,
        "file_counts": file_counts,
    }


# Markers that indicate a continuation session or non-user-intent messages
_SKIP_PATTERNS = [
    "This session is being continued",
    "This is a continuation",
    "/recall",
    "<command-message>",
    "<system-reminder>",
    "session_utils.py",
    "recall_search.py",
    "recall_autosave.py",
    "[Request interrupted",
    "<local-command-caveat>",
]


def _extract_topic(user_messages: list) -> str:
    """Extract core topic from user messages, skipping boilerplate.

    Returns a concise topic string (<=80 chars).
    """
    # Find the first substantive user message
    topic_msg = ""
    for msg in user_messages:
        if any(pat in msg for pat in _SKIP_PATTERNS):
            continue
        # Skip very short system-like messages
        if len(msg.strip()) < 5:
            continue
        topic_msg = msg.strip()
        break

    if not topic_msg:
        # Fallback: try ALL messages if early ones are all skipped
        for msg in user_messages:
            stripped = msg.strip()
            if len(stripped) >= 10 and not any(pat in stripped for pat in _SKIP_PATTERNS):
                topic_msg = stripped
                break
    if not topic_msg:
        return "未知主题"

    # Normalize line endings
    topic_msg = topic_msg.replace("\r\n", "\n").replace("\r", "\n")

    # Strip common prefixes
    _PREFIX_PATTERNS = [
        "Implement the following plan:",
        "Implement the following plan：",
        "implement the plan:",
    ]
    for prefix in _PREFIX_PATTERNS:
        if topic_msg.lower().startswith(prefix.lower()):
            topic_msg = topic_msg[len(prefix):].strip()
            break

    # Strip leading markdown headers (# anything)
    topic_msg = re.sub(r'^#+\s*', '', topic_msg).strip()

    if not topic_msg:
        return "未知主题"

    # Short messages: use as-is
    if len(topic_msg) <= 60:
        return topic_msg

    # Long messages: extract first sentence (use earliest valid separator)
    best_idx = len(topic_msg)
    for sep in ["。", ".\n", "\n", ". "]:
        idx = topic_msg.find(sep)
        if 10 < idx < 120 and idx < best_idx:
            best_idx = idx
    if best_idx < len(topic_msg):
        return topic_msg[:best_idx].strip()

    # Fallback: truncate
    return topic_msg[:80].strip()


def _classify_activity(user_messages: list, tool_uses: list, file_counts: Counter) -> list:
    """Classify session activity into 1-2 labels based on tools, files, and keywords.

    Returns list of Chinese activity labels (max 2).
    """
    labels = []
    tool_set = set(tool_uses)
    # Only use first 30 user messages for keyword classification (avoid noise in long sessions)
    early_messages = user_messages[:30]
    all_user_text = " ".join(early_messages).lower()
    file_exts = set()
    for fname in file_counts:
        if "." in fname:
            file_exts.add("." + fname.rsplit(".", 1)[-1].lower())

    # Rule-based classification (priority order)
    tex_files = file_exts & {".tex", ".bib", ".cls", ".sty"}
    code_files = file_exts & {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp",
                               ".c", ".go", ".rs", ".rb", ".php", ".vue", ".svelte"}
    has_edit = ("Edit" in tool_set or "Write" in tool_set)

    # 论文写作
    if has_edit and tex_files:
        labels.append("论文写作")
    # 代码开发
    elif has_edit and code_files:
        labels.append("代码开发")

    # Bug fix / debugging (require 3+ keyword hits to avoid false positives)
    bug_keywords = ["bug", "error", "fix", "修复", "报错", "出错", "traceback", "exception"]
    bug_count = sum(all_user_text.count(kw) for kw in bug_keywords)
    if bug_count >= 3:
        labels.append("问题修复")

    # 简历修改 (word boundary; only override if no strong file-type signal already)
    cv_count = sum(len(re.findall(pat, all_user_text))
                   for pat in [r"简历", r"\bcv\b", r"\bresume\b", r"\bcurriculum\b"])
    if cv_count >= 3 and not (tex_files or code_files):
        labels = ["简历修改"]

    # 资料检索
    if "WebSearch" in tool_set or "WebFetch" in tool_set:
        if not labels:
            labels.append("资料检索")

    # 配置/部署
    config_keywords = ["docker", "deploy", "部署", "配置", "安装", "setup"]
    if any(kw in all_user_text for kw in config_keywords) and not labels:
        labels.append("配置部署")

    # Git operations
    git_keywords = ["git", "commit", "merge", "rebase", "pr", "pull request"]
    if any(kw in all_user_text for kw in git_keywords) and not labels:
        labels.append("Git操作")

    # 数据分析
    data_keywords = ["数据", "data", "分析", "analysis", "统计", "可视化", "plot", "chart"]
    data_exts = file_exts & {".csv", ".xlsx", ".ipynb", ".parquet"}
    if (data_exts or any(kw in all_user_text for kw in data_keywords)) and not labels:
        labels.append("数据分析")

    # Fallback
    if not labels:
        if has_edit:
            labels.append("代码编辑")
        elif tool_uses:
            labels.append("技术讨论")
        else:
            labels.append("对话")

    return labels[:2]


def _extract_key_files(file_counts: Counter) -> list:
    """Extract key files with strict filtering.

    Returns up to 5 filenames sorted by frequency.
    """
    _KNOWN_EXTS = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".vue", ".svelte",
        ".java", ".cpp", ".c", ".h", ".go", ".rs", ".rb", ".php", ".swift",
        ".html", ".css", ".scss", ".less",
        ".tex", ".bib", ".cls", ".sty",
        ".md", ".txt", ".rst",
        ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".sql", ".sh", ".bat", ".ps1",
        ".ipynb", ".csv", ".xlsx",
        ".xml", ".svg", ".r", ".m",
        ".dockerfile", ".makefile",
    }
    _EXCLUDE_PATTERNS = {"_meta.json", ".jsonl", ".pyc", ".pyo", ".DS_Store"}

    filtered = []
    for fname, count in file_counts.most_common():
        # Must be at least 4 chars (e.g. "a.py")
        if len(fname) < 4:
            continue
        # Must have a known extension
        if "." not in fname:
            continue
        ext = "." + fname.rsplit(".", 1)[-1].lower()
        if ext not in _KNOWN_EXTS:
            continue
        # Exclude internal/temp files
        if any(pat in fname for pat in _EXCLUDE_PATTERNS):
            continue
        # Exclude glob patterns
        if "*" in fname or "?" in fname:
            continue
        filtered.append(fname)
        if len(filtered) >= 5:
            break

    return filtered


def _is_continuation(user_messages: list) -> bool:
    """Check if this is a continuation session."""
    if not user_messages:
        return False
    first = user_messages[0]
    return ("This session is being continued" in first
            or "This is a continuation" in first)


def _build_natural_summary(topic: str, activities: list, key_files: list,
                           user_messages: list, max_chars: int = 300) -> str:
    """Build a natural language summary from extracted components.

    Format varies by session type:
    - Short session (<10 messages): just the topic
    - Continuation: "延续会话 — {activity}: {topic}"
    - Normal: "{activity}: {topic}。主要涉及 {files}。"
    """
    is_cont = _is_continuation(user_messages)
    is_short = len(user_messages) < 10
    activity_str = "、".join(activities)

    if is_short and not is_cont:
        summary = f"{activity_str}: {topic}" if activities else topic
    elif is_cont:
        summary = f"延续会话 — {activity_str}: {topic}"
    else:
        summary = f"{activity_str}: {topic}"
        if key_files:
            files_str = ", ".join(key_files)
            summary += f"。涉及 {files_str}"

    if len(summary) > max_chars:
        summary = summary[:max_chars - 3] + "..."

    return summary


def summarize_session(jsonl_path: str, max_summary_chars: int = 300) -> dict:
    """Generate a natural language summary and tags from a session .jsonl file.

    Pure rule-based extraction — no LLM API calls.

    Args:
        jsonl_path: Path to the .jsonl session file
        max_summary_chars: Maximum characters for the summary text

    Returns:
        dict with 'summary' (str) and 'tags' (list of str)
    """
    path = Path(_normalize_path(jsonl_path))
    if not path.exists():
        return {"summary": "", "tags": []}

    entries = _parse_jsonl_entries(path)
    if not entries:
        return {"summary": "", "tags": []}

    data = _extract_session_data(entries)
    user_messages = data["user_messages"]
    assistant_messages = data["assistant_messages"]
    tool_uses = data["tool_uses"]
    file_counts = data["file_counts"]

    if not user_messages:
        return {"summary": "", "tags": []}

    topic = _extract_topic(user_messages)
    activities = _classify_activity(user_messages, tool_uses, file_counts)
    key_files = _extract_key_files(file_counts)
    summary = _build_natural_summary(topic, activities, key_files,
                                     user_messages, max_summary_chars)

    tags = _extract_tags(user_messages, assistant_messages, tool_uses,
                         file_counts, activities)

    return {"summary": summary, "tags": tags}


def _extract_tags(user_msgs: list, asst_msgs: list, tool_uses: list,
                  file_counts: Counter, activities: list = None) -> list:
    """Extract precise tags from session content.

    Stricter than before:
    - Language tags: file must appear 2+ times
    - Domain tags: keyword must appear 2+ times in user messages
    - Activity tags: reuse _classify_activity() results
    Target: 4-8 tags.
    """
    tags = set()

    # File extension → language tags (require 2+ occurrences)
    ext_to_lang = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".jsx": "react", ".tsx": "react", ".vue": "vue",
        ".java": "java", ".cpp": "c++", ".c": "c", ".rs": "rust",
        ".go": "go", ".rb": "ruby", ".php": "php", ".swift": "swift",
        ".html": "html", ".css": "css", ".scss": "css",
        ".tex": "latex", ".bib": "latex",
        ".sql": "sql", ".sh": "shell", ".bat": "shell",
        ".ipynb": "jupyter",
    }
    # Aggregate counts by language
    lang_counts = Counter()
    for fname, count in file_counts.items():
        if "." not in fname:
            continue
        ext = "." + fname.rsplit(".", 1)[-1].lower()
        if ext in ext_to_lang:
            lang_counts[ext_to_lang[ext]] += count

    for lang, count in lang_counts.items():
        if count >= 2:
            tags.add(lang)

    # Activity tags from classification
    if activities:
        activity_to_tag = {
            "论文写作": "论文写作", "代码开发": "编程", "问题修复": "调试",
            "简历修改": "简历", "资料检索": "检索", "配置部署": "部署",
            "Git操作": "git", "数据分析": "数据分析",
            "代码编辑": "编程", "技术讨论": "讨论",
        }
        for act in activities:
            if act in activity_to_tag:
                tags.add(activity_to_tag[act])

    # Domain keyword tags (require 2+ occurrences in user text)
    all_user_text = " ".join(user_msgs).lower()
    keyword_map = {
        "论文": "论文", "paper": "论文", "arxiv": "论文",
        "test": "测试", "pytest": "测试", "unittest": "测试",
        "refactor": "重构", "重构": "重构",
        "docker": "docker", "container": "docker",
        "api": "api", "endpoint": "api",
        "database": "数据库", "sql": "数据库",
        "设计": "设计", "design": "设计",
    }
    for keyword, tag in keyword_map.items():
        if all_user_text.count(keyword) >= 2:
            tags.add(tag)

    return sorted(tags)[:8]


def diff_sessions(old_path: str, new_path: str, mode: str = "brief",
                  max_messages: int = 50, max_chars: int = 500) -> str:
    """Compare two versions of a session and extract incremental content.

    Handles both normal growth and compaction scenarios.

    Args:
        old_path: Path to the older .jsonl version
        new_path: Path to the newer .jsonl version
        mode: 'brief' or 'detailed'
        max_messages: Max messages to show
        max_chars: Max chars per message
    """
    old_p = Path(_normalize_path(old_path))
    new_p = Path(_normalize_path(new_path))

    if not old_p.exists():
        return f"Error: Old file not found: {old_path}"
    if not new_p.exists():
        return f"Error: New file not found: {new_path}"

    old_entries = _parse_jsonl_entries(old_p)
    new_entries = _parse_jsonl_entries(new_p)

    # Build ID sets
    old_ids = set(_entry_id(e) for _, e in old_entries)
    new_ids = set(_entry_id(e) for _, e in new_entries)

    # Find incremental (in new but not in old)
    added_ids = new_ids - old_ids
    added_entries = [(ln, e) for ln, e in new_entries if _entry_id(e) in added_ids]

    # Find lost (in old but not in new — likely compacted)
    lost_ids = old_ids - new_ids
    lost_entries = [(ln, e) for ln, e in old_entries if _entry_id(e) in lost_ids]

    # Detect compaction
    has_compaction = any(_is_compact_marker(e) for _, e in new_entries)

    # Stats
    lines = []
    lines.append("=== 版本差异分析 ===")
    lines.append("")
    lines.append(f"旧版本: {len(old_entries)} 条记录")
    lines.append(f"新版本: {len(new_entries)} 条记录")
    lines.append(f"新增:   {len(added_entries)} 条记录")
    lines.append(f"移除:   {len(lost_entries)} 条记录")
    if has_compaction:
        lines.append("⚠ 检测到 compact（上下文压缩）: 部分早期消息已被摘要替代")
    lines.append("")

    # Show added messages (incremental content)
    if added_entries:
        added_readable = _extract_readable(added_entries, mode, max_chars)
        if added_readable:
            lines.append("--- 新增对话内容 ---")
            lines.append("")
            for i, (role, text) in enumerate(added_readable):
                if i >= max_messages:
                    lines.append(f"... 还有 {len(added_readable) - max_messages} 条消息未显示")
                    break
                lines.append(f"[{role}] {text}")
                lines.append("")
        else:
            lines.append("新增记录为工具调用/系统消息，无可读文本内容。")
    else:
        lines.append("两个版本之间无新增对话内容。")

    # Show compacted messages if any
    if lost_entries and has_compaction:
        lost_readable = _extract_readable(lost_entries, mode, max_chars)
        if lost_readable:
            lines.append("")
            lines.append("--- 被 compact 压缩的早期对话 ---")
            lines.append("")
            for i, (role, text) in enumerate(lost_readable):
                if i >= max_messages:
                    lines.append(f"... 还有 {len(lost_readable) - max_messages} 条消息未显示")
                    break
                lines.append(f"[{role}] {text}")
                lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Recall Session Utils")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # extract subcommand
    extract_parser = subparsers.add_parser("extract", help="Extract readable content from a session")
    extract_parser.add_argument("jsonl_path", help="Path to the .jsonl session file")
    extract_parser.add_argument("--mode", choices=["brief", "detailed"], default="brief",
                                help="Extraction mode (default: brief)")
    extract_parser.add_argument("--max-messages", type=int, default=30,
                                help="Maximum messages to extract (default: 30)")
    extract_parser.add_argument("--max-chars", type=int, default=500,
                                help="Maximum characters per message (default: 500)")

    # list subcommand
    list_parser = subparsers.add_parser("list", help="List saved sessions")
    list_parser.add_argument("base_dir", help="Path to the central sessions directory")
    list_parser.add_argument("--category", help="Filter by category")
    list_parser.add_argument("--sort", choices=["modified", "name", "count"], default="modified",
                             help="Sort by: modified (default), name, or count")
    list_parser.add_argument("--limit", type=int, default=0,
                             help="Maximum sessions to show (0 = unlimited)")
    list_parser.add_argument("--detail", action="store_true",
                             help="Show detailed multi-line output per session")

    # search subcommand
    search_parser = subparsers.add_parser("search", help="Search sessions by keyword")
    search_parser.add_argument("base_dir", help="Path to the central sessions directory")
    search_parser.add_argument("keyword", help="Search keyword")
    search_parser.add_argument("--category", help="Filter by category")

    # stats subcommand
    stats_parser = subparsers.add_parser("stats", help="Show statistics overview")
    stats_parser.add_argument("base_dir", help="Path to the central sessions directory")

    # check subcommand
    check_parser = subparsers.add_parser("check", help="Check original file existence")
    check_parser.add_argument("base_dir", help="Path to the central sessions directory")

    # summarize subcommand
    summarize_parser = subparsers.add_parser("summarize", help="Generate structured summary and tags")
    summarize_parser.add_argument("jsonl_path", help="Path to the .jsonl session file")
    summarize_parser.add_argument("--max-chars", type=int, default=300,
                                  help="Maximum characters for summary (default: 300)")

    # diff subcommand
    diff_parser = subparsers.add_parser("diff", help="Compare two versions of a session")
    diff_parser.add_argument("old_path", help="Path to the older .jsonl version")
    diff_parser.add_argument("new_path", help="Path to the newer .jsonl version")
    diff_parser.add_argument("--mode", choices=["brief", "detailed"], default="brief",
                             help="Extraction mode (default: brief)")
    diff_parser.add_argument("--max-messages", type=int, default=50,
                             help="Maximum messages to show (default: 50)")
    diff_parser.add_argument("--max-chars", type=int, default=500,
                             help="Maximum characters per message (default: 500)")

    args = parser.parse_args()

    if args.command == "extract":
        print(extract_session(args.jsonl_path, args.mode, args.max_messages, args.max_chars))
    elif args.command == "list":
        print(list_sessions(args.base_dir, args.category, args.sort, args.limit, args.detail))
    elif args.command == "search":
        print(search_sessions(args.base_dir, args.keyword, args.category))
    elif args.command == "stats":
        print(stats_sessions(args.base_dir))
    elif args.command == "check":
        print(check_sessions(args.base_dir))
    elif args.command == "summarize":
        result = summarize_session(args.jsonl_path, args.max_chars)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "diff":
        print(diff_sessions(args.old_path, args.new_path, args.mode,
                            args.max_messages, args.max_chars))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
