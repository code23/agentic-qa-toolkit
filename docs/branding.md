# Branding your reports

An agency can put its own cover, logo, colours, fonts and voice on every report without
changing the toolkit. The brand lives in a folder of its own, outside the toolkit, and the
toolkit points at it. Updating the toolkit never touches your brand, and your brand never
ends up in a pull request.

## What a brand folder holds

A complete example ships with the qa-standards skill in `brand-example/`.

| File | Required | Used by | What it holds |
|---|---|---|---|
| `brand.json` | yes | exporter | Name, colours, logo, fonts, cover fields, footer |
| logo file | no | exporter | SVG, PNG, WebP or JPEG, named in `brand.json` |
| `fonts/` | no | exporter | WOFF2, WOFF, TTF or OTF files, named in `brand.json` |
| `cover.md` | no | exporter | Cover page layout with placeholders; a standard cover is used without it |
| `report.css` | no | exporter | Extra styling for the HTML and PDF export |
| `brand.md` | no | agent | How reports under this brand read: voice, structure, words to avoid |

`brand.json`:

```json
{
  "name": "Example Agency",
  "colours": { "accent": "#2f5bea", "ink": "#161a23", "muted": "#5b6372", "paper": "#ffffff" },
  "logo": "logo.svg",
  "fonts": {
    "heading": { "family": "Example Sans", "file": "fonts/example-sans-bold.woff2" },
    "body": { "family": "Example Text", "file": "fonts/example-text.woff2" }
  },
  "cover": {
    "prepared_by": "Example Agency QA team",
    "contact": "qa@example.com",
    "confidentiality": "Prepared for the client named on this report."
  },
  "footer": "Example Agency · QA report"
}
```

Only `name` is required. Colours are `#rgb` or `#rrggbb`. Unknown keys are an error, so a
typo does not silently do nothing.

`cover.md` can use `{title}` (the report's first heading), `{date}`, `{brand}`,
`{prepared_by}`, `{contact}` and `{confidentiality}`.

## Set one up

1. Copy `skills/qa-standards/brand-example/` to a folder of your own, outside the toolkit.
   A private repository of its own is a good home if a team shares it.
2. Replace the files with your own and edit `brand.json`.
3. Check it:

   ```bash
   .venv/bin/python skills/qa-standards/scripts/brand_check.py /path/to/your-brand
   ```

4. Point the toolkit at it once, in your shell profile or your agent's environment:

   ```bash
   export QA_BRAND=/path/to/your-brand
   ```

From then on the agent reads your `brand.md` before writing a report, and
`report_export.py` puts your cover, logo, colours, fonts and footer on the HTML and PDF.
Use `--brand /path/to/other-brand` to export one report under a different brand, or
`--no-brand` to export without one.

## What a brand cannot change

- **The method.** Severity, priority, evidence, coverage and the verdict rule come from
  qa-standards. `brand.md` decides how a report reads, not what it concludes.
- **The safety rules.** Every brand file must sit inside the brand folder and is inlined
  into the export. The export still loads nothing from the network: `report.css` may not use
  `@import` or a `url()` that is not a `data:` URI, and an SVG logo is shown as an image, so
  any script or link inside it does nothing.
- **The screenshot checks.** The logo is not counted as a screenshot. A report still fails
  if one of its screenshots is missing or will not load.
