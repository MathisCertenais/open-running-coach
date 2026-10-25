# Domain Docs

How the engineering skills should consume this repo's domain documentation when
exploring the codebase.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root — the canonical vocabulary for every
  coaching metric and running concept the app exposes.
- **`docs/adr/`** — read ADRs that touch the area you are about to work in.
- **`docs/research/`** — literature notes; read the one backing the formula you
  are about to change.

If any of these files do not exist, **proceed silently**. Do not flag their
absence or suggest creating them upfront. `/domain-modeling` (reached via
`/grill-with-docs`) creates them lazily when terms or decisions are resolved.

## File structure

Single-context repo:

```
/
├── GLOSSARY.md
├── CODING_STANDARDS.md
├── docs/
│   ├── adr/
│   │   ├── 0001-sqlite-via-stdlib.md
│   │   └── ...
│   └── research/
└── app/
```

There is no `GLOSSARY-MAP.md` and no per-package glossary: this is one context.

## Use the glossary's vocabulary

When your output names a domain concept — an issue title, a refactor proposal, a
hypothesis, a test name — use the term as defined in `GLOSSARY.md`. In
particular, do not drift between "training load", "TL" and "load score"; the
glossary fixes which word belongs where.

If the concept you need is not in the glossary yet, that is a signal: either you
are inventing language the project does not use (reconsider), or there is a real
gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than
silently overriding it:

> _Contradicts ADR-0003 (stdlib-only runtime dependencies), but worth reopening
> because…_
