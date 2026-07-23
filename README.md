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
- **Auto-Golden Generation**: Opt-in `/speckit.auto-golden` command that uses LLMs to generate golden examples. Later releases add example-output validation before writing.
- **CI/CD Gatekeeper**: Supports `warn` and `strict` modes to block PR merges when behavioral drift is detected.

**v0.4.0 (Applicability improvements):**
- **Hybrid Spec Parsing**: Uses LLM (Gemini-first, then OpenAI) to extract acceptance criteria from natural language. Falls back to regex if no API key is available or supplied.
- **Fixture Sandbox**: Side-effecting vectors get a disposable sandbox — filesystem (tempdir + seed), HTTP (local server + route fixtures), DB (SQLite + schema/seed). Real subprocess runs against these, not production resources.
- **Semantic Comparison**: Drift is no longer binary. `6 vs 6.0` = 0.0 (numeric_tolerance). `[1,2,4] vs [1,2,3]` = 0.33 (partial_list). Match type is shown in the drift report.

**v0.4.2 (Human-gated baselines):**
- **HTTP Proxy Injection**: Plain `http://` calls can be intercepted through subprocess-scoped `HTTP_PROXY` without changing production code.
- **GATED Snapshot Mode**: Empty pure golden files can be initialized from real output only after explicit human approval. There is no `snapshot_mode: "auto"`.

**v0.4.3 (Safer regex extraction):**
- **Structured Regex Fallback**: Regex extraction no longer guesses from loose keywords. It requires a concrete input literal and a concrete output literal in a supported format.

**v0.4.4 (Interactive API keys):**
- **One-run API key prompt**: If no `GEMINI_API_KEY` or `OPENAI_API_KEY` is set and the command is interactive, Golden Demo asks which provider to use and reads the API key for the current run only. The key is not written to config, source files, or disk.

**v0.5.0 (Validated Auto-Golden):**
- **Example-validated Auto-Golden**: `/speckit.auto-golden` now reads vector metadata from `test-vectors.md`, asks the LLM for `execute(input_data)`, and validates `execute(example_input) == expected_output` before writing.
- **Safer write behavior**: Generated golden files are written automatically only after example validation passes. Failed validations require explicit `[y/N]` approval in interactive runs, otherwise they are reported as `SKIPPED` in `suggestions.md`.

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

## Accepted Regex Fallback Spec Formats

When no LLM provider is configured, Golden Demo uses a deterministic regex fallback. This fallback is intentionally strict: it only extracts vectors when both input and output are written as concrete literal values.

Accepted examples:

```text
- Given `[1,2,3]`, returns `6`
- Given input [1,2,3], function returns 6.
- Input: [1,2,3] -> Output: 6
- Input: {"temperature": -5, "max": 0} -> Output: true
```

The fallback accepts literals written in backticks, square brackets, quotes, numbers, JSON-like objects, booleans, or null-like values. It will not extract vague natural language such as:

```text
- The result of their computation must be validated before returns are processed.
- The cold chain validator should return true when temperatures stay within threshold.
```

This is intentional. The regex fallback prefers false negatives over false positives. If your acceptance criteria are natural-language only, either rewrite them in one of the structured formats above or use the optional LLM parser with human review.

## HTTP Proxy Injection — Scope

Golden Demo's proxy injection currently supports plain HTTP (`http://`) calls without any code changes. HTTPS calls are NOT intercepted in this version: the CONNECT tunnel handshake encrypts the request path before it reaches the fixture server, so a standard forward proxy cannot see or match it.

If your real implementation calls HTTPS endpoints, either:
- Point your test config at an `http://` variant of the endpoint, or
- Wait for MITM proxy support (tracked as a future version), or
- Point `real_cmd` at a fixture-aware test harness for this vector

This is an intentional scope decision, not an oversight — MITM interception requires certificate generation and trust-chain handling that adds significant platform-specific complexity.

## GATED Snapshot Mode

Golden Demo can initialize an empty pure golden file from the real implementation only when snapshot mode is explicitly gated:

```json
{
  "real_cmd": "python sum_list.py",
  "input_method": "stdin",
  "snapshot_mode": "gated"
}
```

Supported values are `"off"` and `"gated"`. There is intentionally no `"auto"` mode. In interactive runs, Golden Demo shows the real output and asks:

```text
No golden reference exists. Real code produced: [output]. Accept this as golden truth? [y/N]
```

If the reviewer answers `y`, Golden Demo writes a simple golden function returning that reviewed value. If the reviewer answers `N` or presses Enter, nothing is written. In non-interactive environments, snapshots are saved only as pending suggestions unless an operator passes an explicit approval flag.

⚠️ Snapshot mode captures CURRENT behavior, not CORRECT behavior. If the implementation has a bug on first run, accepting the snapshot will make that bug the accepted baseline. Only use gated snapshot mode for pure functions you have manually verified, or combine with a second reviewer's sign-off.

## Auto-Golden (LLM Generator)

You can automatically fill the empty golden templates using:
```bash
/speckit.auto-golden
```
**Important:**
- **Provider priority:** If both `GEMINI_API_KEY` and `OPENAI_API_KEY` are set, Gemini is used (Golden Demo is Gemini-first). If only one is set, that provider is used automatically.
- If no key is set and the command is interactive, Golden Demo asks for the provider and API key, then scopes that key to the current command process only.
- In non-interactive/CI environments, Golden Demo does not prompt or wait for input. Set `GEMINI_API_KEY` or `OPENAI_API_KEY` in the environment if you want LLM generation there.
- The command validates generated code by running `execute(example_input)` and comparing it to the vector's expected output before writing.
- If validation passes, the golden file is written. If validation fails, Golden Demo shows the generated code and asks for `[y/N]` approval in interactive runs.
- In non-interactive environments, failed validations are never written automatically; they are saved as `SKIPPED` suggestions in `suggestions.md`.

## Installation

```bash
specify extension add --from https://github.com/jasstt/spec-kit-golden-demo/archive/refs/heads/main.zip
```

## Verify

```bash
specify extension list
# ✓ Golden Demo (v0.5.0)
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

## When to Use Golden Demo

**Works well for:**
1. Pure algorithmic functions (parsers, formatters, calculators, validators)
2. Specs that clearly define input/output relationships
3. Refactoring legacy code — copy the old implementation as the golden, test the new one against it (no bootstrap paradox)
4. Same algorithm implemented in multiple languages — verify behavioral parity

**Not suitable for:**
1. UI/UX or end-to-end browser tests
2. Distributed system or network-reliability tests
3. Vague or frequently changing specs
4. Cases where the golden itself is generated by an LLM without human review (LLM vs LLM = no ground truth)

> **Note:** For best results, golden examples should be written by a human expert
> or derived from a known-good existing implementation.

## License

MIT
