# Golden Demo

> A [Spec Kit](https://github.com/github/spec-kit) community extension that
> captures acceptance criteria from your spec as test vectors and produces a
> behavioral drift report after implementation.

**Status: draft / hook-interface validation** — production execution logic is not yet implemented.

---

## What it does

| Hook | Triggers after | Action |
|---|---|---|
| `after_plan` | `/speckit.plan` | Scans `spec.md` + `plan.md` for acceptance criteria → writes `.specify/golden-demo/test-vectors.md` |
| `after_implement` | `/speckit.implement` | Reads `test-vectors.md` → prints `would run: {vector}` for each entry (dry-run) |

Both hooks are **opt-in** (`optional: true`) — Spec Kit will prompt before running either one.

## Installation

```bash
specify extension add --dev /path/to/golden-demo
# veya doğrudan repodan:
specify extension add --from https://github.com/jasstt/spec-kit-golden-demo/archive/refs/heads/main.zip
```

## Verify

```bash
specify extension list
# ✓ Golden Demo (v0.1.0)
```

Then run your normal SDD workflow:

```bash
/speckit.plan   → prompted: "Golden Demo: extract test vectors from spec and plan?"
/speckit.implement → prompted: "Golden Demo: run behavioral drift check?"
```

## File layout

```
golden-demo/
├── extension.yml               # Manifest
├── README.md                   # This file
└── commands/
    ├── extract-vectors.md      # after_plan hook command
    └── check-drift.md          # after_implement hook command
```

## Design notes

This is a **draft for hook-interface validation**, shared with the spec-kit
maintainers to confirm the `after_plan` / `after_implement` seam is correct
before building production logic.

The two genuinely new pieces this extension adds on top of the TDD + converge triad:

1. **Differential oracle** — a second reference implementation as a cross-check,
   independent of the user's implementation.
2. **Zero-TDD path** — behavioral vector synthesis and execution for projects
   that have not opted into TDD.

Both are deferred to a future version. This draft only validates hook wiring.

## License

MIT
