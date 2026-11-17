#!/usr/bin/env python3
"""
review_capture.py - Claude Code Stop hook (claude-review plugin)

After every Claude response, saves the reply to a markdown file you can mark up
(highlights, comments, strikethroughs), then hand back to Claude with /feedback.

Files written (inside REVIEW_DIR, default <project>/.claude/review/):
  latest.md            the newest reply from any conversation - open this and annotate it
  .latest.orig.md      untouched copy, so Claude can see exactly what you changed
  sessions/<name>/     latest.md and .latest.orig.md for one conversation, named
                       <MMDD>-<first words of its first prompt>, so conversations
                       running side by side don't overwrite each other. If you've
                       marked up latest.md and not sent it, a reply from another
                       conversation goes only to its own folder until you do.
  history/             every reply as <time>-<first words of your prompt>.md,
                       plus <same name>-annotated.md if you marked up latest.md.
                       You can also mark up a history file in place; /feedback
                       rebuilds the original from the session transcript.
  feedback.md          running log of your marks and # Feedback notes, one entry per reply

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

import contextlib
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

LEGEND = "<!-- ==highlight==  %%comment%%  ~~cut~~  or edit anything, then run /feedback -->\n"

# Empty section at the bottom for notes on the reply as a whole.
FEEDBACK = "---\n\n# Feedback\n\n<!-- overall notes on the whole reply -->\n"

# Prompts longer than PROMPT_FOLD_AT lines show their first PROMPT_PREVIEW
# lines; the rest goes in a collapsible <details> block.
PROMPT_FOLD_AT = 10
PROMPT_PREVIEW = 5

# Editor context the IDE extensions attach to your message, e.g.
# <ide_opened_file>...</ide_opened_file> or <ide_selection>...</ide_selection>.
IDE_CONTEXT = re.compile(r"<(ide_\w+)>.*?</\1>", re.DOTALL)

HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.DOTALL)
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
STAMP_LINE = re.compile(r"^<!-- session .*? \| (\d{8}-\d{6}) -->$", re.MULTILINE)
SESSION_LINE = re.compile(r"^<!-- session (\S+) \|", re.MULTILINE)
MARKS = re.compile(r"==[^=\n]+==|%%[^%]+?%%|~~[^~\n]+~~")
CONTEXT_CHARS = 60  # how much of the line before a %%comment%% to show with it

# History files are named <stamp>-<first few words of your prompt>.md.
SLUG_WORDS = 6
SLUG_CHARS = 50


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


def has_block(content, kind):
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == kind for b in content
    )


def is_prompt(e):
    """A message you sent, as opposed to a tool result or injected context."""
    if e.get("type") != "user" or e.get("isMeta") or e.get("isSidechain"):
        return False
    return not has_block((e.get("message") or {}).get("content"), "tool_result")


def prompt_text(e):
    """Your prompt as you typed it. Slash commands are stored as
    <command-name>/x</command-name><command-args>...</command-args>."""
    text = IDE_CONTEXT.sub("", text_of((e.get("message") or {}).get("content"))).strip()
    name = COMMAND_NAME.search(text)
    if name:
        args = COMMAND_ARGS.search(text)
        return f"{name.group(1).strip()} {args.group(1).strip() if args else ''}".strip()
    return "" if text.startswith("<") else text  # other system wrappers


def current_turn(entries):
    """(your prompt, [Claude's messages]) for the latest turn. A message is a run
    of text between tool calls, so a turn that talks, edits a file, then talks
    again gives two."""
    start = next((i for i in range(len(entries) - 1, -1, -1) if is_prompt(entries[i])), None)
    prompt = prompt_text(entries[start]) if start is not None else ""
    messages, current = [], []
    for e in entries[(start or -1) + 1:]:
        if e.get("isSidechain") or e.get("type") not in ("assistant", "user"):
            continue
        content = (e.get("message") or {}).get("content")
        t = text_of(content).strip() if e.get("type") == "assistant" else ""
        if t:
            current.append(t)
        if has_block(content, "tool_use") or has_block(content, "tool_result"):
            if current:
                messages.append("\n\n".join(current))
            current = []
    if current:
        messages.append("\n\n".join(current))
    return prompt, messages


def format_reply(messages):
    """One message as is; several split by --- with a heading each, so they show
    up in an outline / table of contents."""
    if len(messages) == 1:
        return messages[0]
    n = len(messages)
    return "\n\n---\n\n".join(f"## Message {i} of {n}\n\n{m}" for i, m in enumerate(messages, 1))


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


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def split_feedback(doc):
    """(everything above the # Feedback heading, what's written under it)."""
    head, sep, tail = doc.rpartition("\n# Feedback\n")
    if not sep:
        return doc, ""
    return head, HTML_COMMENT.sub("", tail).strip()


def marks_in(text):
    """[(text just before the mark on its line, mark)], ignoring HTML comments."""
    text = HTML_COMMENT.sub("", text)
    found = []
    for m in MARKS.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        before = text[max(line_start, m.start() - CONTEXT_CHARS):m.start()].strip()
        found.append((before, m.group()))
    return found


def log_entry(annotated, original, archived_name, thread=None):
    """Markdown for feedback.md: the marks you added and your # Feedback notes.
    None if you only made plain edits (the archived copy still has those).
    thread names the conversation's sessions/ folder, if known."""
    body, notes = split_feedback(annotated)
    already = {m for _, m in marks_in(split_feedback(original)[0])}  # markup Claude wrote itself
    added = [(before, m) for before, m in marks_in(body) if m not in already]
    if not added and not notes:
        return None

    when = re.search(r"^# Claude's reply · (.+)$", annotated, re.MULTILINE)
    prompt = re.search(r"^# Your prompt\n\n> (.*)$", annotated, re.MULTILINE)
    title = when.group(1) if when else archived_name
    if prompt and prompt.group(1).strip():
        snippet = prompt.group(1).strip()
        title += f' · "{snippet[:70]}{"…" if len(snippet) > 70 else ""}"'

    link = f"[annotated copy](history/{archived_name})"
    if thread:
        link += f" · conversation `{thread}`"
    lines = [f"## {title}\n", link + "\n"]
    for before, m in added:
        lines.append(f"- {m}" + (f" ← …{before}" if before and m.startswith("%%") else ""))
    if added:
        lines.append("")
    if notes:
        lines.append(notes + "\n")
    return "\n".join(lines) + "\n"


def slug(prompt):
    """A few words of your prompt for the history filename, so you can find a
    reply with Ctrl+P. Slash commands drop their plugin prefix:
    "/claude-review:feedback" -> "feedback"."""
    text = re.sub(r"^/(?:[\w-]+:)?", "", prompt.strip())
    words = re.findall(r"[a-z0-9]+", text.lower())[:SLUG_WORDS]
    return "-".join(words)[:SLUG_CHARS].strip("-")


def history_name(stamp, prompt, reply=""):
    """<stamp>-<slug>.md. A slash command like /feedback says little on its own,
    so the first words of the reply follow it: feedback-your-notes-are-all."""
    s = slug(prompt)
    if prompt.strip().startswith("/") and reply:
        s = "-".join(p for p in (s, slug(reply)) if p)[:SLUG_CHARS].strip("-")
    return f"{stamp}-{s}.md" if s else f"{stamp}.md"


def find_history(history_dir, stamp):
    """Filename of the reply saved at stamp (not an -annotated copy), or None."""
    try:
        names = sorted(os.listdir(history_dir))
    except OSError:
        return None
    return next((n for n in names if n.startswith(stamp) and n.endswith(".md")
                 and not n.endswith("-annotated.md")), None)


def render(prompt, messages, session_id, stamp, now):
    """The markdown file for one reply - shared with review_diff.py, which
    rebuilds originals from the transcript and needs the exact same output."""
    parts = [LEGEND]
    if env_flag("REVIEW_INCLUDE_PROMPT", 1) and prompt:
        parts.append(f"# Your prompt\n\n{format_prompt(prompt)}\n\n---\n")
    # H1 so it sits above any ## / ### headings inside the reply itself.
    parts.append(f"# Claude's reply · {now:%b} {now.day}, {now:%H:%M}\n")  # no %-d on Windows
    parts.append(f"<!-- session {session_id} | {stamp} -->\n")
    parts.append(format_reply(messages) + "\n")
    parts.append(FEEDBACK)
    return "\n".join(parts)


def sent_key(review_dir, path):
    """Key for a file in the "sent" record: the filename for history files (as
    before), the path inside REVIEW_DIR for latest.md files, since every
    conversation folder has one."""
    if os.path.basename(path) == "latest.md":
        return os.path.relpath(path, review_dir).replace(os.sep, "/")
    return os.path.basename(path)


def already_sent(review_dir, path):
    return load_state(review_dir).get("sent", {}).get(sent_key(review_dir, path)) == sha(path)


def mark_sent(review_dir, path):
    """Remember that this version of the file has been handled, so /feedback
    doesn't pick it again or log it twice."""
    state = load_state(review_dir)
    state.setdefault("sent", {})[sent_key(review_dir, path)] = sha(path)
    save_state(review_dir, state)


def write_text(path, text):
    """Write all at once (temp file, then rename), so a reader never sees half a file."""
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


@contextlib.contextmanager
def locked(review_dir, wait=10, stale=30):
    """Let one hook or /feedback at a time change the review folder, so two
    conversations finishing together don't trip over each other. Gives up
    waiting after `wait` seconds and goes ahead rather than hang the session."""
    os.makedirs(review_dir, exist_ok=True)
    path = os.path.join(review_dir, ".lock")
    deadline = time.time() + wait
    fd = None
    while fd is None:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):  # Windows: PermissionError while it's being deleted
            try:
                if time.time() - os.path.getmtime(path) > stale:  # left behind by a crash
                    os.remove(path)
                    continue
            except OSError:
                continue
            if time.time() > deadline:
                break
            time.sleep(0.05)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
            try:
                os.remove(path)
            except OSError:
                pass


def append_log(review_dir, entry):
    log = os.path.join(review_dir, "feedback.md")
    new_log = not os.path.exists(log)
    with open(log, "a", encoding="utf-8") as f:
        if new_log:
            f.write("# Feedback log\n\nYour notes on each reply, oldest first.\n\n")
        f.write(entry)


def session_of(text):
    m = SESSION_LINE.search(text or "")
    return m.group(1) if m else None


def orig_of(latest):
    """The untouched copy that sits next to a latest.md."""
    return os.path.join(os.path.dirname(latest), ".latest.orig.md")


def owner_of(latest):
    """Session id of the reply in a latest.md, read from its untouched copy."""
    try:
        return session_of(read_text(orig_of(latest)))
    except OSError:
        return None


def is_annotated(latest):
    orig = orig_of(latest)
    return os.path.exists(latest) and os.path.exists(orig) and sha(latest) != sha(orig)


def thread_name(review_dir, session_id):
    """Name of a conversation's sessions/ folder, or None if it has none yet."""
    return load_state(review_dir).get("sessions", {}).get(session_id)


def thread_dir(review_dir, session_id, prompt="", reply="", now=None):
    """sessions/<name>/ for a conversation, naming it on its first reply:
    <MMDD>-<first words of the prompt>, e.g. 1116-refactor-the-auth-flow."""
    state = load_state(review_dir)
    threads = state.setdefault("sessions", {})
    name = threads.get(session_id)
    if not name:
        now = now or datetime.datetime.now()
        base = history_name(f"{now:%m%d}", prompt, reply)[:-3]
        taken = set(threads.values())
        name, n = base, 2
        while name in taken or os.path.exists(os.path.join(review_dir, "sessions", name)):
            name, n = f"{base}-{n}", n + 1
        threads[session_id] = name
        save_state(review_dir, state)
    path = os.path.join(review_dir, "sessions", name)
    os.makedirs(path, exist_ok=True)
    return path


def unique(directory, name):
    """name, or name with -2, -3... before .md if that file already exists."""
    stem, n = name[:-3], 2
    while os.path.exists(os.path.join(directory, name)):
        name, n = f"{stem}-{n}.md", n + 1
    return name


def archive(review_dir, latest, stamp):
    """Keep a marked-up latest.md in history/ before it's replaced, and add what
    you wrote to the running log in feedback.md."""
    history_dir = os.path.join(review_dir, "history")
    original = read_text(orig_of(latest))
    # Name it after the reply you annotated, so it sorts next to that reply's
    # plain copy. The stamp comes from the untouched original, which you can't
    # have edited by accident.
    prev = STAMP_LINE.search(original)
    if prev:
        plain = find_history(history_dir, prev.group(1))
        name = f"{plain[:-3] if plain else prev.group(1)}-annotated.md"
    else:
        name = f"{stamp}-prev-annotated.md"
    archived = os.path.join(history_dir, unique(history_dir, name))
    shutil.copy2(latest, archived)
    mark_sent(review_dir, archived)  # logged below, so /feedback skips it
    annotated = read_text(latest)
    entry = log_entry(annotated, original, os.path.basename(archived),
                      thread_name(review_dir, session_of(original)))
    if entry:
        append_log(review_dir, entry)


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


def save_state(review_dir, state):
    os.makedirs(review_dir, exist_ok=True)
    write_text(state_path(review_dir), json.dumps(state, indent=2) + "\n")


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

    entries = read_transcript(data.get("transcript_path"))
    prompt, messages = current_turn(entries)
    # The transcript may not have the final message written yet when the hook fires.
    final = (data.get("last_assistant_message") or "").strip()
    if final and not (messages and messages[-1].endswith(final)):
        messages.append(final)
    reply = format_reply(messages) if messages else ""
    if not reply or len(reply) < env_int("REVIEW_MIN_CHARS", 0):
        return

    with locked(review_dir):
        target = capture(review_dir, data.get("session_id") or "?", prompt, messages)

    words = prompt.lower().split()
    if "#noopen" in words:
        want_open = False
    elif "#open" in words:
        want_open = True
    argv = open_command(target) if want_open else None
    if argv:
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def capture(review_dir, session_id, prompt, messages):
    """Save the reply; return the latest.md to open."""
    history_dir = os.path.join(review_dir, "history")
    os.makedirs(history_dir, exist_ok=True)
    now = datetime.datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    own = os.path.join(thread_dir(review_dir, session_id, prompt, messages[0], now), "latest.md")
    latest = os.path.join(review_dir, "latest.md")

    # If you annotated the previous reply, keep that version instead of losing it.
    if is_annotated(own):
        archive(review_dir, own, stamp)
    # The shared latest.md may hold another conversation's reply. If you've marked
    # it up and not sent it yet, leave it for that conversation's /feedback.
    write_latest = True
    if is_annotated(latest):
        if owner_of(latest) in (session_id, None) or already_sent(review_dir, latest):
            archive(review_dir, latest, stamp)
        else:
            write_latest = False

    doc = render(prompt, messages, session_id, stamp, now)
    for path in (own, latest) if write_latest else (own,):
        write_text(path, doc)
        write_text(orig_of(path), doc)

    if env_flag("REVIEW_KEEP_HISTORY", 1):
        name = unique(history_dir, history_name(stamp, prompt, messages[0]))
        write_text(os.path.join(history_dir, name), doc)
    return latest if write_latest else own


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never break the session
        print(f"review_capture: {exc}", file=sys.stderr)
    sys.exit(0)
