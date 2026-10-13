---
description: Send this change to the hosted QA bot for a QA run (args: optional URL, depth quick|deep|release, focus)
argument-hint: [url] [quick|deep|release] [focus]
---
Send this work to the hosted QA bot. Arguments from the user: $ARGUMENTS

1. Work out the URL to test: use one in the arguments; otherwise the staging or preview URL for this project from the README, deploy config or recent command output. Do not open env or secret files to find it. Never a localhost URL: the QA bot is hosted and cannot reach it. If you cannot find a public URL, ask me for it and stop.
2. Depth: quick by default; deep or release only if the arguments say so.
3. Write a brief of 2-6 sentences: what changed (from the current branch, recent commits, the diff and this conversation), which pages, flows, forms and roles to focus on, and anything known to be risky. Never include passwords, tokens, keys or customer data.
4. Save the brief to a temporary file with your file-writing tool, not through the shell, so nothing in it is run as a command. Then run, with each value in single quotes: qa-send --url '<url>' --depth <depth> --brief-file '<temp file>' --project '<repo or folder name>' --branch '<current branch>' --commit '<short sha>'. If a value itself contains a single quote, stop and tell me instead of running it. Delete the temporary file afterwards.
5. Tell me in one line whether it was sent, then carry on with what we were doing. Results come back in the QA bot's chat.
