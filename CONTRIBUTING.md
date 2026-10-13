# Contributing

Thanks for looking. The most useful contribution is a clear issue.

## What we accept

- **Bug reports**: a script gives a wrong result, crashes, or a skill instruction contradicts
  another one.
- **False positives and misses**: a check flags something that is fine, or misses something
  it claims to catch. A small HTML sample that shows it is ideal.
- **Ideas**: a check, an edition or a document you think is missing.

**Pull requests are not accepted at the moment.** Open an issue instead and describe the
change. This keeps every change going through the same checks before it ships, and it will
be revisited as the project settles.

## A good issue has

1. What you ran (the command, or what you asked your agent to do) and on which edition.
2. What you expected and what happened.
3. The smallest page or file that reproduces it. Use made-up content.

Never include credentials, customer data, or the name or address of a site you do not own.

## Security problems

Do not open a public issue. See [SECURITY.md](SECURITY.md).

## Working on the code yourself

The project is MIT licensed, so you are free to fork it. To run the checks:

```bash
python3 -m venv .venv && .venv/bin/pip install -r skills/qa-site-audit/scripts/requirements.txt -r skills/qa-standards/scripts/requirements.txt
(cd tests/node && npm ci)
tools/check.sh
```

`tools/check.sh` runs every test suite, the package build scan and the link check, and
prints one line per check. See [docs/maintaining.md](docs/maintaining.md) for the layout.
