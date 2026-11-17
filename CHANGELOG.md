# Changelog

Bump `version` in `.claude-plugin/plugin.json` with every release; Claude Code
only refreshes an installed plugin when the version changes.

## 0.5.0 - 2026-11-16

- Mark up any reply in `history/` in place and run `/feedback`; no copying.
  The untouched original is rebuilt from the session transcript, and your
  marks and `# Feedback` notes go into `feedback.md` as usual.
- `/feedback <file>` takes a path, a stamp (`203155`) or words from a history
  filename (`brainstorm`). With no argument it uses the review file open in
  your editor, then `latest.md` if changed, then the most recently edited
  history file not yet sent.
- History files are named `<time>-<first words of your prompt>.md`, so Ctrl+P
  can find them. After a slash command, the first words of the reply are added
  (`<time>-feedback-your-notes-are-all-under.md`), since `/feedback` alone
  tells replies apart. Annotated copies follow: `<same name>-annotated.md`.

## 0.4.1 - 2026-10-26

- `latest.md` captures everything Claude said since your prompt, not just the
  last message. When a reply has several messages (text between tool calls),
  each gets a `## Message N of M` heading, separated by `---`.
- `# Your prompt` shows the prompt that started the turn, including slash
  commands with their arguments (e.g. `/claude-review:feedback ...`), instead
  of falling back to an older typed prompt.

## 0.4.0 - 2026-10-19

- `latest.md` ends with an empty `# Feedback` section for notes on the reply
  as a whole; `/feedback` responds to it last.
- `feedback.md` keeps a running log of your annotations: each time a new reply
  replaces one you marked up, the marks you added and your `# Feedback` notes
  are appended, with a link to the archived copy.
- Annotated copies in `history/` are named after the reply they belong to
  (`<time>-annotated.md`, next to `<time>.md`) instead of the time the next
  reply arrived (`<time>-prev-annotated.md`).

## 0.3.0 - 2026-10-08

- `/review view` opens `latest.md` straight away.
- `/review clear` deletes the archived replies in `history/`.
- `latest.md` is easier to scan: `# Your prompt` and `# Claude's reply · <time>`
  headings, and a one-line legend instead of five.
- Prompts longer than 10 lines show their first 5; the rest is folded into a
  collapsible section.

## 0.2.0 - 2026-10-08

- `/review on | off | open | noopen | reset | status` changes capture and
  auto-open per project, stored in `<REVIEW_DIR>/.state.json` and taking
  precedence over the `REVIEW_*` variables.

## 0.1.1 - 2026-10-08

- Quote the prompt you actually typed when the IDE attaches editor context.

## 0.1.0 - 2026-10-08

- First release: a Stop hook saves each reply to `.claude/review/latest.md`
  (plus an untouched copy and a history), and `/feedback` responds to your
  markup.
- Per-message `#open` / `#noopen` overrides for opening `latest.md`.
