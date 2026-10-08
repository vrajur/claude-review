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

All three render natively in Obsidian (`%%…%%` is Obsidian's comment syntax:
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
| `/review view` | open `latest.md` now |
| `/review clear` | delete the archived replies in `history/` |
| `/review status` | show the current settings and where they come from |
| `/review reset` | forget the switches, back to the `REVIEW_*` variables |

Per message: put `#noopen` in your prompt to skip opening for that reply, or
`#open` to force it. These win over everything else.

Tip: in VS Code, set `"workbench.editor.revealIfOpen": true` so reopening
`latest.md` reuses its existing tab instead of opening a duplicate.
