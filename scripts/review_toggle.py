#!/usr/bin/env python3
"""
review_toggle.py - backs the /review command (claude-review plugin)

  review_toggle.py off | on        stop / resume capturing replies in this project
  review_toggle.py noopen | open   stop / resume opening latest.md after each reply
  review_toggle.py reset           forget both switches (fall back to REVIEW_* env vars)
  review_toggle.py view            open this conversation's newest reply now
  review_toggle.py clear           delete history/ and the per-conversation folders in sessions/
  review_toggle.py [status]        print the current settings

  --session <id>                   the conversation running /review, for view and status

Switches live in <REVIEW_DIR>/.state.json, which review_capture.py reads.
Run from the project root (or with CLAUDE_PROJECT_DIR set).
"""

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_capture as rc  # noqa: E402
from review_capture import get_review_dir, load_state, open_command, save_state, settings, state_path  # noqa: E402

ACTIONS = {
    "off": ("enabled", False),
    "on": ("enabled", True),
    "noopen": ("open", False),
    "open": ("open", True),
}


def parse_args(argv):
    """(action, session id or None). An unsubstituted ${CLAUDE_SESSION_ID}
    arrives empty or as the literal text."""
    rest, session = list(argv), None
    if "--session" in rest:
        i = rest.index("--session")
        session = rest[i + 1].strip("\"'") if i + 1 < len(rest) else ""
        del rest[i:i + 2]
    if not session or "$" in session or "{" in session:
        session = None
    action = (rest[0].lower() if rest else "status").lstrip("-")
    return action, session


def own_latest(review_dir, session):
    """The latest.md showing this conversation's newest reply: the shared one if
    it holds it, otherwise the conversation's own copy in sessions/."""
    latest = os.path.join(review_dir, "latest.md")
    name = rc.thread_name(review_dir, session) if session else None
    if not name or rc.owner_of(latest) == session:
        return latest
    return os.path.join(review_dir, "sessions", name, "latest.md")


def describe(review_dir, session=None):
    enabled, want_open = settings(review_dir)
    state = load_state(review_dir)
    source = lambda key: "set by /review" if key in state else "default from settings"
    name = rc.thread_name(review_dir, session) if session else None
    here = f" This conversation: sessions/{name}/latest.md." if name else ""
    return (
        f"Review capture: {'ON' if enabled else 'OFF'} ({source('enabled')}); "
        f"auto-open: {'ON' if want_open else 'OFF'} ({source('open')}). "
        f"Folder: {review_dir}.{here}"
    )


def view(review_dir, session=None):
    latest = own_latest(review_dir, session)
    if not os.path.exists(latest):
        return f"No reply captured yet ({latest} doesn't exist)."
    argv = open_command(latest)
    if not argv:
        return f"No editor found to open it (set REVIEW_OPEN_CMD). File: {latest}"
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Opened {latest}"


def empty(directory):
    """Delete everything in directory; return how many items there were."""
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return 0
    for name in names:
        path = os.path.join(directory, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    return len(names)


def clear(review_dir):
    with rc.locked(review_dir):
        history = empty(os.path.join(review_dir, "history"))
        threads = empty(os.path.join(review_dir, "sessions"))
        state = load_state(review_dir)
        if state.pop("sessions", None) is not None:
            save_state(review_dir, state)
    return (
        f"Cleared {history} item(s) from history/ and {threads} conversation folder(s) from sessions/. "
        f"latest.md and feedback.md were kept; feedback.md's links to annotated copies no longer resolve."
    )


def main(argv):
    action, session = parse_args(argv)
    review_dir = get_review_dir()
    if action == "view":
        print(view(review_dir, session))
        return 0
    if action == "clear":
        print(clear(review_dir))
        return 0
    if action == "status":
        pass
    elif action == "reset":
        # Forget only the switches; conversation names and what's been sent stay.
        with rc.locked(review_dir):
            state = load_state(review_dir)
            if os.path.exists(state_path(review_dir)):
                for key in ("enabled", "open"):
                    state.pop(key, None)
                save_state(review_dir, state)
    elif action in ACTIONS:
        key, value = ACTIONS[action]
        with rc.locked(review_dir):
            state = load_state(review_dir)
            state[key] = value
            save_state(review_dir, state)
    else:
        print(f"Unknown option '{action}'. Use: on, off, open, noopen, view, clear, reset, status.")
        return 1
    print(describe(review_dir, session))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
