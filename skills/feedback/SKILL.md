---
name: feedback
description: Read my markup on your last reply (.claude/review/latest.md) and respond to each annotation.
disable-model-invocation: true
---

I've marked up one of your earlier replies. Respond to my annotations.

1. Read `.claude/review/latest.md` (my annotated copy). If `REVIEW_DIR` is set in the environment, the files are in that folder instead (relative to the project unless absolute). If I named a different file here, read that instead: $ARGUMENTS
2. Read `.latest.orig.md` from the same folder (the untouched original) and compare. Every difference is feedback from me, whether or not it uses the markup below.
3. Interpret the markup:
   - `==text==` - I'm highlighting this: it matters, I agree, or I want more on it.
   - `%%comment%%` - my note about the text immediately before it. (Older files may use `[[comment]]` for the same thing.)
   - `~~text~~` - I disagree with this or want it removed.
   - Text I added, deleted or rewrote - treat it as a correction or preference.
4. Reply by going through my annotations in order. For each one, quote a few words of the part I marked so it's clear which spot you mean, then respond: answer the question, defend or revise the point, expand on it, or act on it.
5. If my notes ask for changes to code or files, make them.
6. Finish with one or two sentences on what changed in your overall view, if anything did.
