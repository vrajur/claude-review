---
name: feedback
description: Read my markup on one of your replies (latest.md, or any reply in history/) and respond to each annotation.
disable-model-invocation: true
argument-hint: "[file | stamp | words from a history filename]"
---

I've marked up one of your earlier replies. Respond to my annotations.

1. Find what I changed. Run this with the Bash tool from the project root, replacing `<skill base directory>` with the base directory shown above for this skill:

   ```
   python3 "<skill base directory>/../../scripts/review_diff.py" --session "${CLAUDE_SESSION_ID}" $ARGUMENTS
   ```

   If I didn't name a file but my message shows I have a file from the review folder open in the IDE (`latest.md`, or anything in `sessions/` or `history/`), add `--open "<that path>"`, so the script tries that file first.

   If the script finds nothing but lists marked-up files from other conversations, tell me which ones and stop. Don't respond to them unless I name one.

   The script picks the file, finds the untouched original, and prints the file's path, where the original came from, and a diff. Every difference is feedback from me, whether or not it uses the markup below. Read the annotated file too, for context. If the file isn't `latest.md`, start your reply with one line naming it.

   If the script says the original isn't available, check whether the reply is still in this conversation and compare against that. Otherwise work from the markup and the `# Feedback` notes, and tell me that plain rewrites may have been missed.
2. Interpret the markup:
   - `==text==` - I'm highlighting this: it matters, I agree, or I want more on it.
   - `%%comment%%` - my note about the text immediately before it. (Older files may use `[[comment]]` for the same thing.)
   - `~~text~~` - I disagree with this or want it removed.
   - Text I added, deleted or rewrote - treat it as a correction or preference.
   - Anything I wrote under the `# Feedback` heading at the bottom - my notes on the reply as a whole.
3. Reply by going through my annotations in order, ending with the `# Feedback` notes if there are any. For each one, quote a few words of the part I marked so it's clear which spot you mean, then respond: answer the question, defend or revise the point, expand on it, or act on it.
4. If my notes ask for changes to code or files, make them.
5. Finish with one or two sentences on what changed in your overall view, if anything did.
