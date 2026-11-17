#!/usr/bin/env python3
"""
review_diff.py - backs the /feedback command (claude-review plugin)

  review_diff.py [file | stamp | words from the filename] [--open <path>]

Works out which reply you marked up, finds the untouched original, and prints a
diff for Claude to respond to.

Which file, in order:
  1. the one you name: a path, a stamp like 203155, or words from a history
     filename like "brainstorm" (the most recently edited match wins)
  2. --open <path>: the file open in your editor, if you've changed it
  3. latest.md, if you've changed it
  4. the most recently edited file in history/ you haven't sent yet

Where the original comes from:
  latest.md                  .latest.orig.md
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
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_capture as rc  # noqa: E402

# A history file saved by the hook has a modification time within a moment of
# its stamp; anything later means you've edited it.
EDIT_GRACE_SECONDS = 10
STAMP = re.compile(r"^(\d{8}-\d{6})")


def parse_args(argv):
    target, open_file, rest = [], None, list(argv)
    while rest:
        a = rest.pop(0)
        if a == "--open" and rest:
            open_file = rest.pop(0)
        else:
            target.append(a)
    return " ".join(target).strip().strip("\"'").lstrip("@"), (open_file or "").strip("\"'").lstrip("@")


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


def already_sent(review_dir, path):
    sent = rc.load_state(review_dir).get("sent", {})
    return sent.get(os.path.basename(path)) == rc.sha(path)


def has_changes(review_dir, path):
    """Cheap check that you've marked this file up and not sent it yet."""
    latest = os.path.join(review_dir, "latest.md")
    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(latest):
        return rc.sha(latest) != rc.sha(os.path.join(review_dir, ".latest.orig.md"))
    if already_sent(review_dir, path):
        return False
    name = os.path.basename(path)
    if name.endswith("-annotated.md"):
        return True
    made = stamp_time(name)
    return bool(made) and os.path.getmtime(path) - made.timestamp() > EDIT_GRACE_SECONDS


def resolve(arg, review_dir):
    """Path for what you typed, or None."""
    history_dir = os.path.join(review_dir, "history")
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    for base in (project, review_dir, history_dir):
        p = os.path.join(base, arg)  # an absolute arg ignores base
        if os.path.isfile(p):
            return os.path.normpath(p)
    if arg.lower() in ("latest", "latest.md"):
        return os.path.join(review_dir, "latest.md")
    words = arg.lower().split()
    matches = [os.path.join(history_dir, n) for n in history_files(history_dir)
               if all(w in n.lower() for w in words)]
    return max(matches, key=os.path.getmtime) if matches else None


def pick(review_dir, open_file):
    if open_file and os.path.isfile(open_file) and has_changes(review_dir, open_file):
        return os.path.normpath(open_file)
    latest = os.path.join(review_dir, "latest.md")
    if os.path.exists(latest) and has_changes(review_dir, latest):
        return latest
    # -annotated copies are archives the Stop hook already logged; name one to use it.
    history_dir = os.path.join(review_dir, "history")
    edited = [p for p in (os.path.join(history_dir, n) for n in history_files(history_dir))
              if not p.endswith("-annotated.md") and has_changes(review_dir, p)]
    # A newer modification time can also come from copying or syncing, so
    # confirm the content really differs before choosing a file.
    for p in sorted(edited, key=os.path.getmtime, reverse=True):
        original, _ = original_of(review_dir, p)
        if original is not None and original == rc.read_text(p):
            rc.mark_sent(review_dir, os.path.basename(p), rc.sha(p))  # untouched: don't check it again
            continue
        return p
    return None


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
    session = re.search(r"^<!-- session (\S+) \|", text, re.MULTILINE)
    if not m or not session:
        return None, "the file has no session line to find its transcript by"
    stamp = m.group(1)
    path = transcript_path(session.group(1))
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
    return rc.render(prompt, messages, session.group(1), stamp, saved_at), None


def original_of(review_dir, path):
    """(original text or None, where it came from / why it's missing)."""
    name = os.path.basename(path)
    if name == "latest.md":
        orig = os.path.join(review_dir, ".latest.orig.md")
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
    if already_sent(review_dir, path):
        return
    name = os.path.basename(path)
    entry = rc.log_entry(annotated, original or "", name)
    if entry:
        log = os.path.join(review_dir, "feedback.md")
        new_log = not os.path.exists(log)
        with open(log, "a", encoding="utf-8") as f:
            if new_log:
                f.write("# Feedback log\n\nYour notes on each reply, oldest first.\n\n")
            f.write(entry)
    rc.mark_sent(review_dir, name, rc.sha(path))


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a code page
    except AttributeError:
        pass
    arg, open_file = parse_args(argv)
    review_dir = rc.get_review_dir()
    path = resolve(arg, review_dir) if arg else pick(review_dir, open_file)
    if not path:
        if arg:
            print(f"No file matches '{arg}' (looked for a path, then history/ filenames containing those words).")
        else:
            print("Found nothing marked up: latest.md matches its original and no history/ file has unsent edits.")
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
    if os.path.basename(path) != "latest.md":  # the Stop hook logs latest.md itself
        log_history(review_dir, path, annotated, original)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
