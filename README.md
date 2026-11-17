# claude-review

A Claude Code plugin for marking up Claude's replies like a draft.

After every reply, a Stop hook saves it to `.claude/review/latest.md` (plus an
untouched copy and a history). Annotate the file, then run `/feedback` and
Claude responds to each mark in order.

| Markup | Meaning |
|---|---|
| `==text==` | highlight: this matters / agree / say more |
| `%%comment%%` | your note on the text just before it |
| `~~text~~` | disagree / cut this |
| any other edit | treated as a correction or preference |

For notes on the reply as a whole, write under the `# Feedback` heading at the
bottom of the file.

When the next reply replaces `latest.md`, your annotated copy is archived in
`history/`, and the marks you added plus your `# Feedback` notes are appended
to `.claude/review/feedback.md`, so you can look back over everything in one
place.

## Several conversations at once

Each conversation also keeps its newest reply in its own folder, named after
the date and its first prompt:
`sessions/1116-refactor-the-auth-flow/latest.md`. With two conversations
running, mark up each one's own file. `/feedback` in a conversation looks at
its own file first, so the two never pick up each other's notes.

`latest.md` still shows the newest reply from any conversation. If you mark it
up, it waits for you: replies from other conversations go only to their own
folders until you run `/feedback` in the conversation it belongs to.
`/review status` shows the current conversation's folder.

## Mark up an older reply

Every reply is also saved in `history/`, named after the time and the first
few words of your prompt, e.g. `20261116-101204-can-we-start-by-brainstorming.md`.
To respond to an older reply, find it (in VS Code: Ctrl+P, then `hist brainstorm`),
mark it up in place, and run `/feedback`. There's nothing to copy:
`/feedback` uses the file you have open, then `latest.md` if you changed it, then
the most recently edited history file (this conversation's first). You can also name the file:
`/feedback brainstorm`, `/feedback 101204` or a full path.

`/feedback` rebuilds the untouched original from the session transcript, so it
sees plain edits as well as markup. Claude Code deletes transcripts after
`cleanupPeriodDays` (30 by default); for older replies only your markup and
`# Feedback` notes are picked up.

All three markup styles render natively in Obsidian (`%%…%%` is Obsidian's comment syntax:
visible while editing, hidden in reading view).

## Install

Needs `python3` on PATH (macOS has it; on Windows use python.org, pyenv-win or
the Store build).

```
/plugin marketplace add <path-or-git-url-of-this-repo>
/plugin install claude-review@claude-review
```

Then restart Claude Code (or open `/hooks`) so the hook loads.

## Configure

Optional, in the `env` block of `~/.claude/settings.json`:

```json
"env": {
  "REVIEW_OPEN": "1",
  "REVIEW_MIN_CHARS": "200"
}
```

| Variable | Default | Effect |
|---|---|---|
| `REVIEW_DIR` | `.claude/review` | where files go (relative to the project, or absolute) |
| `REVIEW_OPEN` | `0` | `1` opens `latest.md` after each reply |
| `REVIEW_OPEN_CMD` | VS Code (`code -r`) | command to open it with; the file path is appended |
| `REVIEW_MIN_CHARS` | `0` | skip replies shorter than this |
| `REVIEW_KEEP_HISTORY` | `1` | archive every reply in `history/` |
| `REVIEW_INCLUDE_PROMPT` | `1` | quote your prompt at the top |
| `REVIEW_DISABLE` | `0` | `1` turns the hook off |

## Switch it on and off

`/review` changes settings for the current project. It stores them in
`<REVIEW_DIR>/.state.json`, and they take precedence over the variables above:

| Command | Effect |
|---|---|
| `/review off` / `/review on` | stop / resume capturing replies |
| `/review noopen` / `/review open` | stop / resume opening `latest.md` after each reply |
| `/review view` | open this conversation's newest reply now |
| `/review clear` | delete the archived replies in `history/` and the `sessions/` folders |
| `/review status` | show the current settings, where they come from, and this conversation's folder |
| `/review reset` | forget the switches, back to the `REVIEW_*` variables |

Per message: put `#noopen` in your prompt to skip opening for that reply, or
`#open` to force it. These win over everything else.

Tip: in VS Code, set `"workbench.editor.revealIfOpen": true` so reopening
`latest.md` reuses its existing tab instead of opening a duplicate.
