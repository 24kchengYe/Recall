#!/usr/bin/env python3
"""
Recall Auto-Save — SessionEnd hook script.

Triggered automatically when a Claude Code session ends (Ctrl+C, /exit, Ctrl+D).
Only updates sessions that have been previously saved via /recall save.
If the current session is not in the central directory, silently exits.

Reads JSON from stdin containing: session_id, cwd, transcript_path (from Claude Code hook).
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows terminal encoding
if platform.system() == "Windows" or "MSYS" in os.environ.get("MSYSTEM", ""):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Default central directory
DEFAULT_BASE_PATH = r"D:\claude-sessions"
CLAUDE_PROJECTS_DIR = Path(os.path.expanduser("~")) / ".claude" / "projects"


def _normalize_path(path_str: str) -> str:
    """Convert MSYS-style paths (/c/Users/...) to Windows paths (C:\\Users\\...) if needed."""
    if len(path_str) >= 3 and path_str[0] == "/" and path_str[2] == "/":
        drive_letter = path_str[1].upper()
        return f"{drive_letter}:{path_str[2:]}".replace("/", "\\")
    return path_str


def _safe_load_json(file_path) -> dict:
    """Load JSON file with fallback to fix unescaped Windows backslashes."""
    with open(file_path, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        fixed = re.sub(r'(?<!\\)\\(?![\\"/bfnrtu])', r'\\\\', raw)
        return json.loads(fixed)


def _find_base_path() -> Path:
    """Find the central directory from _config.json or use default."""
    default = Path(_normalize_path(DEFAULT_BASE_PATH))
    config_path = default / "_config.json"
    if config_path.exists():
        try:
            config = _safe_load_json(config_path)
            bp = config.get("basePath", DEFAULT_BASE_PATH)
            return Path(_normalize_path(bp))
        except Exception:
            pass
    return default


def _find_current_session_file(cwd: str) -> tuple:
    """Find the current session's .jsonl file based on cwd.

    Returns (session_id, jsonl_path) or (None, None).
    """
    cwd_normalized = _normalize_path(cwd)

    # Find matching project directory
    if not CLAUDE_PROJECTS_DIR.exists():
        return None, None

    # Try to find project dir by checking sessions-index.json
    matching_project_dir = None
    for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir() or proj_dir.name.startswith("."):
            continue
        idx_file = proj_dir / "sessions-index.json"
        if idx_file.exists():
            try:
                idx = _safe_load_json(idx_file)
                for entry in idx.get("entries", []):
                    proj_path = entry.get("projectPath", "")
                    if proj_path and os.path.normcase(os.path.normpath(proj_path)) == \
                            os.path.normcase(os.path.normpath(cwd_normalized)):
                        matching_project_dir = proj_dir
                        break
            except Exception:
                continue
        if matching_project_dir:
            break

    # Fallback: try path encoding heuristic
    if not matching_project_dir:
        for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
            if not proj_dir.is_dir():
                continue
            # Check if any part of cwd appears in the dir name
            cwd_lower = cwd_normalized.lower().replace("\\", "/")
            dir_name_decoded = proj_dir.name.replace("--", "/").lower()
            # Simple heuristic: if significant parts match
            if len(dir_name_decoded) > 5 and any(
                part in cwd_lower for part in dir_name_decoded.split("/") if len(part) > 3
            ):
                matching_project_dir = proj_dir
                break

    if not matching_project_dir:
        return None, None

    # Find most recently modified .jsonl
    jsonl_files = list(matching_project_dir.glob("*.jsonl"))
    if not jsonl_files:
        return None, None

    jsonl_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    latest = jsonl_files[0]
    session_id = latest.stem  # filename without extension = session ID

    return session_id, latest


def _find_saved_session(base_path: Path, session_id: str) -> tuple:
    """Search central directory for a previously saved session by sessionId.

    Returns (meta_path, meta_dict) or (None, None).
    """
    config_path = base_path / "_config.json"
    if not config_path.exists():
        return None, None

    try:
        config = _safe_load_json(config_path)
    except Exception:
        return None, None

    for cat in config.get("categories", []):
        cat_dir = base_path / cat
        if not cat_dir.exists():
            continue
        for meta_file in cat_dir.glob("*_meta.json"):
            try:
                meta = _safe_load_json(meta_file)
                if meta.get("sessionId") == session_id:
                    return meta_file, meta
            except Exception:
                continue

    return None, None


def _count_messages(jsonl_path: Path) -> int:
    """Count user/assistant messages in a .jsonl file."""
    count = 0
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") in ("user", "assistant"):
                        count += 1
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return count


def _generate_summary(jsonl_path: Path) -> dict:
    """Generate a basic summary from the session file.

    Returns dict with 'abstract' and 'tags' keys.
    """
    try:
        # Import summarize from session_utils if available
        script_dir = Path(__file__).parent
        sys.path.insert(0, str(script_dir))
        from session_utils import summarize_session
        result = summarize_session(str(jsonl_path))
        # Normalize: summarize_session returns "summary" key, we use "abstract"
        if "summary" in result and "abstract" not in result:
            result["abstract"] = result.pop("summary")
        return result
    except (ImportError, AttributeError):
        return {"abstract": "", "tags": []}


def _sync_name_to_sessions_index(session_id: str, name: str, cwd: str):
    """Write the Recall session name back to Claude's sessions-index.json.

    Claude Code auto-generates its own summary, overwriting the user-defined name.
    This re-syncs Recall's name after each autosave so /resume shows the correct name.
    """
    cwd_normalized = _normalize_path(cwd)

    if not CLAUDE_PROJECTS_DIR.exists():
        return

    for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir() or proj_dir.name.startswith("."):
            continue
        idx_file = proj_dir / "sessions-index.json"
        if not idx_file.exists():
            continue
        try:
            idx = _safe_load_json(idx_file)
            entries = idx.get("entries", [])
            updated = False
            for entry in entries:
                if entry.get("sessionId") == session_id:
                    if entry.get("summary") != name:
                        entry["summary"] = name
                        updated = True
                    break
            if updated:
                with open(idx_file, "w", encoding="utf-8") as f:
                    json.dump(idx, f, ensure_ascii=False, indent=2)
        except Exception:
            continue


def _git_commit(base_path: Path, files: list, message: str):
    """Stage files and commit in the central directory's git repo."""
    try:
        # Check if it's a git repo
        git_dir = base_path / ".git"
        if not git_dir.exists():
            return

        add_cmd = ["git", "-C", str(base_path), "add"] + [str(f) for f in files]
        subprocess.run(add_cmd, capture_output=True, timeout=10)

        commit_cmd = ["git", "-C", str(base_path), "commit", "-m", message]
        subprocess.run(commit_cmd, capture_output=True, timeout=10)
    except Exception:
        pass


def _do_autosave(session_id, cwd, transcript_path):
    """Actual autosave logic — runs in a detached background process."""
    # Find base path
    base_path = _find_base_path()
    if not base_path.exists():
        return

    # Determine current session
    if transcript_path:
        tp = Path(_normalize_path(transcript_path))
        if tp.exists():
            session_id = tp.stem
            current_jsonl = tp
        else:
            session_id, current_jsonl = _find_current_session_file(cwd)
    elif session_id:
        current_jsonl = None
        for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
            if not proj_dir.is_dir():
                continue
            candidate = proj_dir / f"{session_id}.jsonl"
            if candidate.exists():
                current_jsonl = candidate
                break
        if not current_jsonl:
            return
    else:
        session_id, current_jsonl = _find_current_session_file(cwd)

    if not session_id or not current_jsonl or not current_jsonl.exists():
        return

    # Check if this session was previously saved
    meta_path, meta = _find_saved_session(base_path, session_id)
    if not meta_path or not meta:
        return

    category = meta.get("category", "")
    name = meta.get("name", "")
    backup_file = meta.get("backupFile", "")

    if not backup_file:
        return

    backup_path = Path(_normalize_path(backup_file))

    try:
        shutil.copy2(str(current_jsonl), str(backup_path))
        msg_count = _count_messages(current_jsonl)
        summary_data = _generate_summary(current_jsonl)

        now = datetime.now(timezone.utc).isoformat()
        meta["modified"] = now
        meta["saved"] = now
        meta["messageCount"] = msg_count
        if summary_data.get("abstract"):
            meta["abstract"] = summary_data["abstract"]
        if summary_data.get("tags"):
            meta["tags"] = summary_data["tags"]

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        _sync_name_to_sessions_index(session_id, name, cwd)

        rel_backup = backup_path.relative_to(base_path)
        rel_meta = meta_path.relative_to(base_path)
        _git_commit(
            base_path,
            [str(rel_backup), str(rel_meta)],
            f"autosave: {name} ({category}) - {msg_count}条消息"
        )
    except Exception as e:
        print(f"[recall autosave] warning: {e}", file=sys.stderr)


def _parse_background_args():
    """Parse CLI args when running in --background mode."""
    session_id = ""
    cwd = os.getcwd()
    transcript_path = ""
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--session-id" and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif args[i] == "--cwd" and i + 1 < len(args):
            cwd = args[i + 1]
            i += 2
        elif args[i] == "--transcript-path" and i + 1 < len(args):
            transcript_path = args[i + 1]
            i += 2
        else:
            i += 1
    return session_id, cwd, transcript_path


def main():
    # If called with --background flag, we ARE the detached process
    if "--background" in sys.argv:
        session_id, cwd, transcript_path = _parse_background_args()
        _do_autosave(session_id, cwd, transcript_path)
        return

    # Read hook input from stdin (must happen in foreground before detaching)
    try:
        raw = sys.stdin.read()
        if raw.strip():
            hook_data = json.loads(raw)
        else:
            hook_data = {}
    except (json.JSONDecodeError, Exception):
        hook_data = {}

    session_id = hook_data.get("session_id", "")
    cwd = hook_data.get("cwd", "") or os.getcwd()
    transcript_path = hook_data.get("transcript_path", "")

    # Otherwise, spawn a detached background process and exit immediately.
    # This prevents double Ctrl+C from cancelling the hook.
    script = os.path.abspath(__file__)
    cmd = [
        sys.executable, script, "--background",
        "--session-id", session_id,
        "--cwd", cwd,
        "--transcript-path", transcript_path,
    ]

    try:
        # On Windows/MSYS: CREATE_NO_WINDOW + DETACHED_PROCESS
        creation_flags = 0
        if platform.system() == "Windows" or "MSYS" in os.environ.get("MSYSTEM", ""):
            CREATE_NO_WINDOW = 0x08000000
            DETACHED_PROCESS = 0x00000008
            creation_flags = CREATE_NO_WINDOW | DETACHED_PROCESS

        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
            start_new_session=True,
        )
    except Exception:
        # Fallback: just run inline if detach fails
        _do_autosave(session_id, cwd, transcript_path)


if __name__ == "__main__":
    main()
