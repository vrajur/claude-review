# Changelog

Bump `version` in `.claude-plugin/plugin.json` with every release; Claude Code
only refreshes an installed plugin when the version changes.

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
