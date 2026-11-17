---
name: review
description: Turn reply capture for /feedback on or off, change whether latest.md opens automatically, open this conversation's newest reply now, or clear the history and per-conversation folders. Usage - /review on | off | open | noopen | view | clear | reset | status
disable-model-invocation: true
argument-hint: on | off | open | noopen | view | clear | reset | status
---

Run this command with the Bash tool from the project root, replacing `<skill base directory>` with the base directory shown above for this skill:

```
python3 "<skill base directory>/../../scripts/review_toggle.py" $ARGUMENTS --session "${CLAUDE_SESSION_ID}"
```

Then reply with the script's output in one short line and nothing else. Don't change any other files.
