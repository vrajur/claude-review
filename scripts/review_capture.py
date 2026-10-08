#!/usr/bin/env python3
"""
review_capture.py - Claude Code Stop hook (claude-review plugin)

After every Claude response, saves the reply to a markdown file you can mark up
(highlights, comments, strikethroughs), then hand back to Claude with /feedback.

Files written (inside REVIEW_DIR, default <project>/.claude/review/):
  latest.md            the newest reply - open this and annotate it
  .latest.orig.md      untouched copy, so Claude can see exactly what you changed
  history/             older replies (and your annotated versions, if you edited them)

Configuration - environment variables, easiest set in the "env" block of
~/.claude/settings.json (all optional):
  REVIEW_DIR            where to write files (relative to the project, or absolute)
  REVIEW_KEEP_HISTORY   1 = archive every reply in history/ (default 1)
  REVIEW_INCLUDE_PROMPT 1 = put your prompt at the top for context (default 1)
  REVIEW_MIN_CHARS      skip replies shorter than this, e.g. "Done." (default 0)
  REVIEW_OPEN           1 = open latest.md after each reply (default 0)
  REVIEW_OPEN_CMD       command to open it with, file path appended
                        (default: VS Code, "code -r", found on PATH or in its
                        usual install location on Windows/macOS/Linux)
  REVIEW_DISABLE        1 = turn the hook off without editing settings (default 0)

Per-project switches - set with the /review command, stored in
<REVIEW_DIR>/.state.json, and taking precedence over the variables above:
  /review off | on      stop / resume capturing replies
  /review noopen | open change whether latest.md opens after each reply
  /review view          open latest.md now
  /review clear         delete the archived replies in history/
  /review status        show the current settings
  /review reset         forget the switches, back to the variables above

Per-message overrides - put one of these anywhere in your prompt:
  #noopen               don't open latest.md for this reply (still saved)
  #open                 open latest.md for this reply even if opening is off

The hook never blocks Claude and never prints to stdout. Errors go to stderr,
which shows up only in Claude Code's debug log.
"""

import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

LEGEND = "<!-- ==highlight==  %%comment%%  ~~cut~~  or edit anything, then run /feedback -->\n"

# Prompts longer than PROMPT_FOLD_AT lines show their first PROMPT_PREVIEW
# lines; the rest goes in a collapsible <details> block.
PROMPT_FOLD_AT = 10
PROMPT_PREVIEW = 5

# Editor context the IDE extensions attach to your message, e.g.
# <ide_opened_file>...</ide_opened_file> or <ide_selection>...</ide_selection>.
IDE_CONTEXT = re.compile(r"<(ide_\w+)>.*?</\1>", re.DOTALL)


def env_flag(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def text_of(content):
    """Pull plain text out of a transcript message's content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
        )
    return ""


def read_transcript(path):
    entries = []
    if not path or not os.path.exists(path):
        return entries
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def last_user_prompt(entries):
    """Most recent message you typed (skips tool results and meta entries)."""
    for e in reversed(entries):
        if e.get("type") != "user" or e.get("isMeta"):
            continue
        content = (e.get("message") or {}).get("content")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        ):
            continue
        text = IDE_CONTEXT.sub("", text_of(content)).strip()
        if text and not text.startswith("<"):  # skip command/system wrappers
            return text
    return ""


def last_reply_from_transcript(entries):
    """Fallback: all assistant text since your last prompt."""
    chunks = []
    for e in reversed(entries):
        if e.get("type") == "user":
            content = (e.get("message") or {}).get("content")
            is_tool_result = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            )
            if not is_tool_result and not e.get("isMeta"):
                break
        elif e.get("type") == "assistant":
            t = text_of((e.get("message") or {}).get("content")).strip()
            if t:
                chunks.append(t)
    return "\n\n".join(reversed(chunks))


def sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def find_vscode():
    """Full path to the VS Code launcher. Hooks often lack it on PATH, and on
    Windows Popen can't run the bare name 'code' (it's code.cmd)."""
    found = shutil.which("code")
    if found:
        return found
    candidates = [
        # Windows (user install, then system install)
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Microsoft VS Code", "bin", "code.cmd"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft VS Code", "bin", "code.cmd"),
        # macOS (system Applications, then ~/Applications)
        "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
        os.path.expanduser("~/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"),
        # Linux (snap, then distro packages)
        "/snap/bin/code",
        "/usr/bin/code",
    ]
    return next((p for p in candidates if os.path.exists(p)), None)


def open_command(path):
    """argv that opens path: REVIEW_OPEN_CMD if set, else VS Code. None if unavailable."""
    custom = os.environ.get("REVIEW_OPEN_CMD", "").strip()
    if custom:
        argv = shlex.split(custom, posix=os.name != "nt")
        exe = shutil.which(argv[0])  # resolve .cmd/.bat shims on Windows
        if not exe:
            return None
        return [exe] + argv[1:] + [path]
    code = find_vscode()
    return [code, "-r", path] if code else None


def quote(lines):
    return "\n".join("> " + l for l in lines)


def format_prompt(prompt):
    """Your prompt as a blockquote, folding everything past the first few lines if it's long."""
    lines = prompt.splitlines()
    if len(lines) <= PROMPT_FOLD_AT:
        return quote(lines)
    rest = lines[PROMPT_PREVIEW:]
    return (
        f"{quote(lines[:PROMPT_PREVIEW])}\n\n"
        f"<details><summary>Show the rest ({len(rest)} more lines)</summary>\n\n"
        f"{quote(rest)}\n\n"
        f"</details>"
    )


def get_review_dir(cwd=None):
    project = os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
    review_dir = os.environ.get("REVIEW_DIR", os.path.join(".claude", "review"))
    if not os.path.isabs(review_dir):
        review_dir = os.path.join(project, review_dir)
    return os.path.normpath(review_dir)


def state_path(review_dir):
    return os.path.join(review_dir, ".state.json")


def load_state(review_dir):
    """Switches set by /review: {"enabled": bool, "open": bool}, either key optional."""
    try:
        with open(state_path(review_dir), encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def settings(review_dir):
    """Effective (enabled, open): /review switches win over environment variables."""
    state = load_state(review_dir)
    enabled = state.get("enabled", not env_flag("REVIEW_DISABLE", 0))
    want_open = state.get("open", env_flag("REVIEW_OPEN", 0))
    return bool(enabled), bool(want_open)


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))  # tolerate a BOM (PowerShell pipes add one)
    review_dir = get_review_dir(data.get("cwd"))
    enabled, want_open = settings(review_dir)
    if not enabled:
        return
    history_dir = os.path.join(review_dir, "history")
    os.makedirs(history_dir, exist_ok=True)

    entries = read_transcript(data.get("transcript_path"))
    reply = (data.get("last_assistant_message") or "").strip()
    if not reply:
        reply = last_reply_from_transcript(entries).strip()
    if not reply or len(reply) < env_int("REVIEW_MIN_CHARS", 0):
        return

    latest = os.path.join(review_dir, "latest.md")
    orig = os.path.join(review_dir, ".latest.orig.md")
    now = datetime.datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    when = f"{now:%b} {now.day}, {now:%H:%M}"  # e.g. "Oct 8, 13:31" (no %-d on Windows)

    # If you annotated the previous reply, keep that version instead of losing it.
    if os.path.exists(latest) and os.path.exists(orig) and sha(latest) != sha(orig):
        shutil.copy2(latest, os.path.join(history_dir, f"{stamp}-prev-annotated.md"))

    prompt = last_user_prompt(entries)
    parts = [LEGEND]
    if env_flag("REVIEW_INCLUDE_PROMPT", 1) and prompt:
        parts.append(f"# Your prompt\n\n{format_prompt(prompt)}\n\n---\n")
    # H1 so it sits above any ## / ### headings inside the reply itself.
    parts.append(f"# Claude's reply · {when}\n")
    parts.append(f"<!-- session {data.get('session_id', '?')} | {stamp} -->\n")
    parts.append(reply + "\n")
    doc = "\n".join(parts)

    for path in (latest, orig):
        with open(path, "w", encoding="utf-8") as f:
            f.write(doc)

    if env_flag("REVIEW_KEEP_HISTORY", 1):
        with open(os.path.join(history_dir, f"{stamp}.md"), "w", encoding="utf-8") as f:
            f.write(doc)

    words = prompt.lower().split()
    if "#noopen" in words:
        want_open = False
    elif "#open" in words:
        want_open = True
    argv = open_command(latest) if want_open else None
    if argv:
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never break the session
        print(f"review_capture: {exc}", file=sys.stderr)
    sys.exit(0)
