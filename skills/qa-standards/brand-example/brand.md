# Example Agency: how our QA reports read

The agent reads this file before writing a report for this brand. It covers voice and
structure only. The method in qa-standards (severity, priority, evidence, coverage and the
verdict rule) always wins over anything here.

## Voice

- Write as the agency to its client: first person plural ("we tested"), plain English, short
  sentences. British or American spelling: pick one and keep to it.
- Lead with what works before what does not. Describe problems as work to do, not blame.
- State findings plainly. No intensifiers ("very", "extremely") and no claims the evidence
  cannot back ("every", "never", "always").
- Never name another client in a report.

## Structure

The report keeps every section qa-standards requires. On top of that:

- The exporter adds the cover from `brand.json` and `cover.md`.
- Open the executive summary with one sentence on what was tested and when.
- Before the findings, add a short "What works well" section: three to five points, each
  with its evidence.
- Close with the next steps in the order we recommend doing them.

## Words we avoid

- "seamless", "robust", "cutting-edge", "leverage"
