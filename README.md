# Golden Demo

> A [Spec Kit](https://github.com/github/spec-kit) community extension that
> captures acceptance criteria from your spec as test vectors and produces a
> behavioral drift report after implementation.

**Status: beta** — fully functional deterministic behavioral oracle.

---

## How it works

**v0.2.0 (behavioral execution):**
- `after_plan` → extract vectors + input/output pairs + empty golden templates
- `after_implement` → read manually implemented golden files → execute both golden and real implementations → compare outputs → deterministic drift score + report

**v0.3.0 (Advanced Oracle Features):**
- **Cross-Language Support**: Test implementations written in Node.js, Go, or Bash against Python golden examples via CLI args or `stdin`.
- **Deterministic Fuzzing**: Automatically generates edge-case test vectors for generic types (`type:list[int]`) using a fixed seed (`42`).
- **Auto-Golden Generation**: Opt-in `/speckit.auto-golden` command that uses LLMs to generate golden examples (requires explicit human `[y/n]` approval).
- **CI/CD Gatekeeper**: Supports `warn` and `strict` modes to block PR merges when behavioral drift is detected.

## Warn vs. Strict Mode

Golden Demo can act as a strict gatekeeper in your CI/CD pipelines. It is controlled by the `GOLDEN_DEMO_MODE` environment variable.

- `GOLDEN_DEMO_MODE=warn` (Default): If drift is detected, a `[!]` warning is printed and the drift report is saved, but the exit code is `0` (build is not blocked).
- `GOLDEN_DEMO_MODE=strict`: If drift is detected, the process exits with code `1`, causing your CI pipeline to fail immediately.

*Best Practice:* Start with `warn` mode to let your team get used to drift reports, then upgrade to `strict` mode when the team is ready.

## Cross-Language Support (`stdin`)

Golden Demo can test real implementations written in any language. 
Configure `.specify/golden-demo/config.json`:
```json
{
  "real_cmd": "node sum_list.js",
  "input_method": "stdin",
  "input_size_threshold_bytes": 4096
}
```
If `input_method` is `"arg"`, inputs are passed via CLI arguments. If `"stdin"`, they are piped. Large inputs automatically fall back to `stdin` based on the threshold.

## Auto-Golden (LLM Generator)

You can automatically fill the empty golden templates using:
```bash
/speckit.auto-golden
```
**Important:**
- **Provider priority:** If both `GEMINI_API_KEY` and `OPENAI_API_KEY` are set, Gemini is used (Golden Demo is Gemini-first). If only one is set, that provider is used automatically.
- You must set either `OPENAI_API_KEY` or `GEMINI_API_KEY` in your environment.
- The command will print proposed code to your console and wait for a `[y/N]` approval before saving anything to disk.
- To bypass human approval in pipelines, pass the `--auto-approve` flag. Without it, non-interactive environments will skip writing to disk and save suggestions to `suggestions.md`.

## Installation

```bash
specify extension add --from https://github.com/jasstt/spec-kit-golden-demo/archive/refs/heads/main.zip
```

## Verify

```bash
specify extension list
# ✓ Golden Demo (v0.3.0)
```

## File layout

```
golden-demo/
├── extension.yml               # Manifest
├── README.md                   # This file
└── commands/
    ├── extract-vectors.md      # after_plan hook command
    ├── check-drift.md          # after_implement hook command
    └── auto-golden.md          # Optional LLM generation command
```

## License

MIT
