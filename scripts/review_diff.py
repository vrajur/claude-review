#!/usr/bin/env python3
"""
review_diff.py - backs the /feedback command (claude-review plugin)

  review_diff.py [file | stamp | words from the filename] [--open <path>] [--session <id>]

Works out which reply you marked up, finds the untouched original, and prints a
diff for Claude to respond to.

--session is the conversation running /feedback. Without it, the script looks
for the transcript that just sent a /feedback command.

Which file, in order (only files you've changed and not sent yet):
  1. the one you name: a path, a stamp like 203155, or words from a history
     filename like "brainstorm" (the most recently edited match wins)
  2. --open <path>: the file open in your editor
  3. this conversation's sessions/<name>/latest.md
  4. latest.md, unless it holds another conversation's reply
  5. the most recently edited file in history/, this conversation's first

Where the original comes from:
  latest.md                  .latest.orig.md next to it
  history/<name>-annotated   history/<name>.md
  history/<name>.md          rebuilt from the session transcript (Claude Code
                             deletes transcripts after cleanupPeriodDays, 30 by
                             default; after that only your markup can be found)

For a history file, your marks and # Feedback notes are added to feedback.md,
the same as the Stop hook does when it archives an annotated latest.md.
"""

import datetime
import difflib
import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_capture as rc  # noqa: E402

# A history file saved by the hook has a modification time within a moment of
# its stamp; anything later means you've edited it.
EDIT_GRACE_SECONDS = 10
STAMP = re.compile(r"^(\d{8}-\d{6})")


def parse_args(argv):
    target, opts, rest = [], {"--open": "", "--session": ""}, list(argv)
    while rest:
        a = rest.pop(0)
        if a in opts:
            opts[a] = rest.pop(0) if rest else ""
        else:
            target.append(a)
    clean = lambda s: s.strip().strip("\"'").lstrip("@")
    return clean(" ".join(target)), clean(opts["--open"]), clean(opts["--session"])


def tail_entries(path, size=512 * 1024):
    """Transcript entries from the end of a file, without reading all of it."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - size))
        lines = f.read().decode("utf-8", "replace").splitlines()[1:]  # first may be cut off
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def guess_session(within=300):
    """Id of the conversation that just sent /feedback, for when the skill
    couldn't pass it: the newest recent transcript whose last prompt is one."""
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    now = time.time()
    recent = [p for p in glob.glob(os.path.join(config, "projects", "*", "*.jsonl"))
              if now - os.path.getmtime(p) < within]
    for path in sorted(recent, key=os.path.getmtime, reverse=True):
        try:
            entries = tail_entries(path)
        except OSError:
            continue
        last = next((e for e in reversed(entries) if rc.is_prompt(e)), None)
        if last and re.match(r"/(?:[\w-]+:)?feedback\b", rc.prompt_text(last)):
            return os.path.basename(path)[:-len(".jsonl")]
    return None


def current_session(given):
    # An unsubstituted ${CLAUDE_SESSION_ID} arrives empty or as the literal text.
    if given and "$" not in given and "{" not in given:
        return given
    return guess_session()


def thread_latest(review_dir, session):
    name = rc.thread_name(review_dir, session) if session else None
    return os.path.join(review_dir, "sessions", name, "latest.md") if name else None


def all_thread_latests(review_dir):
    return glob.glob(os.path.join(review_dir, "sessions", "*", "latest.md"))


def stamp_time(name):
    m = STAMP.match(name)
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(1), "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def history_files(history_dir):
    try:
        return [n for n in os.listdir(history_dir) if n.endswith(".md") and STAMP.match(n)]
    except OSError:
        return []


def has_changes(review_dir, path):
    """Cheap check that you've marked this file up and not sent it yet."""
    if rc.already_sent(review_dir, path):
        return False
    if os.path.basename(path) == "latest.md":
        return rc.is_annotated(path)
    name = os.path.basename(path)
    if name.endswith("-annotated.md"):
        return True
    made = stamp_time(name)
    return bool(made) and os.path.getmtime(path) - made.timestamp() > EDIT_GRACE_SECONDS


def resolve(arg, review_dir, session):
    """Path for what you typed, or None."""
    history_dir = os.path.join(review_dir, "history")
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    for base in (project, review_dir, history_dir):
        p = os.path.join(base, arg)  # an absolute arg ignores base
        if os.path.isfile(p):
            return os.path.normpath(p)
    if arg.lower() in ("latest", "latest.md"):
        own = thread_latest(review_dir, session)
        return own if own and os.path.exists(own) else os.path.join(review_dir, "latest.md")
    words = arg.lower().split()
    matches = [os.path.join(history_dir, n) for n in history_files(history_dir)
               if all(w in n.lower() for w in words)]
    return max(matches, key=os.path.getmtime) if matches else None


def pick(review_dir, open_file, session):
    if open_file and os.path.isfile(open_file) and has_changes(review_dir, open_file):
        return os.path.normpath(open_file)
    own = thread_latest(review_dir, session)
    if own and os.path.exists(own) and has_changes(review_dir, own):
        return own
    latest = os.path.join(review_dir, "latest.md")
    if (os.path.exists(latest) and has_changes(review_dir, latest)
            and (not session or rc.owner_of(latest) in (session, None))):
        return latest
    if not session:  # can't tell which conversation this is: any marked-up latest.md
        changed = [p for p in all_thread_latests(review_dir) if has_changes(review_dir, p)]
        if changed:
            return max(changed, key=os.path.getmtime)
    # -annotated copies are archives the Stop hook already logged; name one to use it.
    history_dir = os.path.join(review_dir, "history")
    edited = [p for p in (os.path.join(history_dir, n) for n in history_files(history_dir))
              if not p.endswith("-annotated.md") and has_changes(review_dir, p)]
    # Newest first, but this conversation's replies before other conversations'.
    edited.sort(key=os.path.getmtime, reverse=True)
    if session:
        edited.sort(key=lambda p: rc.session_of(rc.read_text(p)) != session)
    for p in edited:
        # A newer modification time can also come from copying or syncing, so
        # confirm the content really differs before choosing a file.
        original, _ = original_of(review_dir, p)
        if original is not None and original == rc.read_text(p):
            rc.mark_sent(review_dir, p)  # untouched: don't check it again
            continue
        return p
    return None


def waiting_elsewhere(review_dir, session):
    """Marked-up latest.md files that belong to other conversations."""
    files = [os.path.join(review_dir, "latest.md")] + all_thread_latests(review_dir)
    return [os.path.relpath(p, review_dir).replace(os.sep, "/") for p in files
            if os.path.exists(p) and has_changes(review_dir, p) and rc.owner_of(p) != session]


def transcript_path(session):
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    found = glob.glob(os.path.join(config, "projects", "*", f"{session}.jsonl"))
    return found[0] if found else None


def entry_time(e):
    t = e.get("timestamp")
    try:
        return datetime.datetime.fromisoformat(t.replace("Z", "+00:00")) if t else None
    except ValueError:
        return None


def rebuild(text):
    """(original, None) rebuilt from the transcript, or (None, reason)."""
    m = rc.STAMP_LINE.search(text)
    session = rc.session_of(text)
    if not m or not session:
        return None, "the file has no session line to find its transcript by"
    stamp = m.group(1)
    path = transcript_path(session)
    if not path:
        return None, "its session transcript is gone (Claude Code deletes them after cleanupPeriodDays)"
    saved_at = datetime.datetime.strptime(stamp, "%Y%m%d-%H%M%S").astimezone()
    entries = rc.read_transcript(path)
    prompts = [i for i, e in enumerate(entries) if rc.is_prompt(e)]
    # The turn is the last prompt sent before the reply was saved, up to the next prompt.
    start = None
    for i in prompts:
        t = entry_time(entries[i])
        if t and t <= saved_at:
            start = i
    if start is None:
        return None, "couldn't find the reply in its session transcript"
    end = next((i for i in prompts if i > start), len(entries))
    prompt, messages = rc.current_turn(entries[:end])
    if not messages:
        return None, "couldn't find the reply in its session transcript"
    return rc.render(prompt, messages, session, stamp, saved_at), None


def original_of(review_dir, path):
    """(original text or None, where it came from / why it's missing)."""
    name = os.path.basename(path)
    if name == "latest.md":
        orig = rc.orig_of(path)
        if os.path.exists(orig):
            return rc.read_text(orig), ".latest.orig.md"
        return None, ".latest.orig.md is missing"
    if name.endswith("-annotated.md"):
        plain = os.path.join(os.path.dirname(path), name[: -len("-annotated.md")] + ".md")
        if os.path.exists(plain):
            return rc.read_text(plain), f"history/{os.path.basename(plain)}"
    text, why = rebuild(rc.read_text(path))
    return (text, "rebuilt from the session transcript") if text else (None, why)


def log_history(review_dir, path, annotated, original):
    """Add your marks to feedback.md, once per version of the file."""
    if rc.already_sent(review_dir, path):
        return
    thread = rc.thread_name(review_dir, rc.session_of(annotated))
    entry = rc.log_entry(annotated, original or "", os.path.basename(path), thread)
    if entry:
        rc.append_log(review_dir, entry)
    rc.mark_sent(review_dir, path)


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a code page
    except AttributeError:
        pass
    arg, open_file, session = parse_args(argv)
    review_dir = rc.get_review_dir()
    with rc.locked(review_dir):
        return run(review_dir, arg, open_file, current_session(session))


def run(review_dir, arg, open_file, session):
    path = resolve(arg, review_dir, session) if arg else pick(review_dir, open_file, session)
    if not path:
        if arg:
            print(f"No file matches '{arg}' (looked for a path, then history/ filenames containing those words).")
            return 1
        print("Found nothing marked up in this conversation's latest.md, the shared latest.md "
              "or history/ that hasn't been sent yet.")
        others = waiting_elsewhere(review_dir, session) if session else []
        if others:
            print("Marked up, from other conversations (run /feedback there, or name the file here): "
                  + ", ".join(others))
        return 1

    annotated = rc.read_text(path)
    original, source = original_of(review_dir, path)
    print(f"Annotated file: {path}")
    if original is None:
        print(f"Original: not available - {source}.")
        print("Work from the markup and the # Feedback notes; plain rewrites can't be told apart from the original.")
    else:
        print(f"Original: {source}")
        diff = list(difflib.unified_diff(original.splitlines(True), annotated.splitlines(True),
                                         "original", "annotated", n=2))
        print("".join(diff) if diff else "No differences from the original.")
    if os.path.basename(path) == "latest.md":
        # The Stop hook logs latest.md when it's replaced; just note it's been sent,
        # so it's not picked again and another conversation's reply can replace it.
        rc.mark_sent(review_dir, path)
    else:
        log_history(review_dir, path, annotated, original)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
