#!/usr/bin/env python3
"""
review_toggle.py - backs the /review command (claude-review plugin)

  review_toggle.py off | on        stop / resume capturing replies in this project
  review_toggle.py noopen | open   stop / resume opening latest.md after each reply
  review_toggle.py reset           forget both switches (fall back to REVIEW_* env vars)
  review_toggle.py view            open latest.md now
  review_toggle.py clear           delete the archived replies in history/
  review_toggle.py [status]        print the current settings

Switches live in <REVIEW_DIR>/.state.json, which review_capture.py reads.
Run from the project root (or with CLAUDE_PROJECT_DIR set).
"""

import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from review_capture import get_review_dir, load_state, open_command, settings, state_path  # noqa: E402

ACTIONS = {
    "off": ("enabled", False),
    "on": ("enabled", True),
    "noopen": ("open", False),
    "open": ("open", True),
}


def describe(review_dir):
    enabled, want_open = settings(review_dir)
    state = load_state(review_dir)
    source = lambda key: "set by /review" if key in state else "default from settings"
    return (
        f"Review capture: {'ON' if enabled else 'OFF'} ({source('enabled')}); "
        f"auto-open: {'ON' if want_open else 'OFF'} ({source('open')}). "
        f"Folder: {review_dir}"
    )


def view(review_dir):
    latest = os.path.join(review_dir, "latest.md")
    if not os.path.exists(latest):
        return f"No reply captured yet ({latest} doesn't exist)."
    argv = open_command(latest)
    if not argv:
        return f"No editor found to open it (set REVIEW_OPEN_CMD). File: {latest}"
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Opened {latest}"


def clear(review_dir):
    history_dir = os.path.join(review_dir, "history")
    try:
        names = os.listdir(history_dir)
    except FileNotFoundError:
        names = []
    for name in names:
        path = os.path.join(history_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    return f"Cleared {len(names)} item(s) from {history_dir}"


def main(argv):
    action = (argv[0].lower() if argv else "status").lstrip("-")
    review_dir = get_review_dir()
    if action == "view":
        print(view(review_dir))
        return 0
    if action == "clear":
        print(clear(review_dir))
        return 0
    if action == "status":
        pass
    elif action == "reset":
        try:
            os.remove(state_path(review_dir))
        except FileNotFoundError:
            pass
    elif action in ACTIONS:
        key, value = ACTIONS[action]
        state = load_state(review_dir)
        state[key] = value
        os.makedirs(review_dir, exist_ok=True)
        with open(state_path(review_dir), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
    else:
        print(f"Unknown option '{action}'. Use: on, off, open, noopen, view, clear, reset, status.")
        return 1
    print(describe(review_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
