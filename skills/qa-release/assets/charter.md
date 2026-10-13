# Release QA Charter

Goal: <complete>

Scope IN: <complete>

Scope OUT: <complete>

Environment: <complete exact URL, deployment, browsers, accounts and data state>

Risks: <complete and map each top risk to coverage.csv>

Oracle: <complete specifications, invariants, provider contracts and judgement boundaries>

## Authority and safety

- Named test accounts and fixtures: <complete>
- Permitted safe mutations: <complete>
- Provider mode and credential boundary: <complete>
- Money cap: <complete or not applicable>
- Merge authority: <complete>
- Sandbox/preview deploy authority: <complete>
- Production writes/deploys: prohibited unless separately and explicitly authorised
- Cleanup and rollback: <complete>

## Verdict rule

FAIL while any in-scope S1/S2 remains open or any top risk has zero executable coverage.

