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
import sys
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
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
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
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                sessions.append(meta)
            except Exception:
                continue

    return sessions


def list_sessions(base_dir: str, category: str = None, sort_by: str = "modified", limit: int = 0) -> str:
    """List all saved sessions in the central directory.

    Args:
        base_dir: Path to the central sessions directory
        category: Optional category filter
        sort_by: Sort key — 'modified' (default), 'name', or 'count'
        limit: Maximum number of sessions to show (0 = unlimited)
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

    # Format as table
    lines = []
    lines.append(f"{'#':<4} {'名称':<25} {'类别':<8} {'消息数':<6} {'最后修改':<12} {'来源项目':<30}")
    lines.append("-" * 90)

    for i, s in enumerate(sessions, 1):
        name = _truncate(s.get("name", "unnamed"), 24)
        cat = s.get("category", "?")
        count = s.get("messageCount", "?")
        modified = s.get("modified", "?")
        if isinstance(modified, str) and len(modified) >= 10:
            modified = modified[:10]
        project = s.get("originalProject", "?")
        # Shorten project path
        if len(project) > 29:
            project = "..." + project[-26:]
        lines.append(f"{i:<4} {name:<25} {cat:<8} {str(count):<6} {modified:<12} {project:<30}")

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
    lines.append(f"{'#':<4} {'名称':<25} {'类别':<8} {'消息数':<6} {'最后修改':<12} {'来源项目':<30}")
    lines.append("-" * 90)

    for i, s in enumerate(matches, 1):
        name = _truncate(s.get("name", "unnamed"), 24)
        cat = s.get("category", "?")
        count = s.get("messageCount", "?")
        modified = s.get("modified", "?")
        if isinstance(modified, str) and len(modified) >= 10:
            modified = modified[:10]
        project = s.get("originalProject", "?")
        if len(project) > 29:
            project = "..." + project[-26:]
        lines.append(f"{i:<4} {name:<25} {cat:<8} {str(count):<6} {modified:<12} {project:<30}")

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
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
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
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
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
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
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
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
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
        print(list_sessions(args.base_dir, args.category, args.sort, args.limit))
    elif args.command == "search":
        print(search_sessions(args.base_dir, args.keyword, args.category))
    elif args.command == "stats":
        print(stats_sessions(args.base_dir))
    elif args.command == "check":
        print(check_sessions(args.base_dir))
    elif args.command == "diff":
        print(diff_sessions(args.old_path, args.new_path, args.mode,
                            args.max_messages, args.max_chars))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
