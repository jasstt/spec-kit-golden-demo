# Extraction Regex Fix Test

## Scope

This report covers the v0.4.3 deterministic regex fallback fix. No NLP or LLM parser was used for these tests.

## Diagnosis

The previous fallback parser selected any bullet line containing `return`, then applied these loose patterns:

```python
input_match = re.search(r'(?:input|list|type) (type:\w+\[?\w*\]?|\[.*?\]|\w+)', text, re.IGNORECASE)
return_match = re.search(r'returns? (\[.*?\]|\w+)', text, re.IGNORECASE)
```

Because `\w+` accepts any word, ordinary prose could become fake input/output values.

Example:

```text
- The list of orders returns their status when queried.
```

Old result:

```json
[
  {
    "example_input": "of",
    "expected_output": "their"
  }
]
```

The current demo false-positive sentence behaved similarly:

```text
- The result of their computation must be validated before returns are processed.
```

Old result:

```json
[
  {
    "example_input": null,
    "expected_output": "are"
  }
]
```

## New Rule

The regex fallback now requires both sides of a concrete pair:

- a `given` or `input` marker followed by a concrete literal
- a `returns` or `output` marker followed by a concrete literal

Accepted literal forms include backticks, lists, quoted strings, numbers, JSON-like objects, booleans, and null-like values.

## Test Results

| Case | Old Regex | New Regex | Result |
|---|---:|---:|---|
| `The list of orders returns their status...` | 1 vector: `of` -> `their` | 0 vectors | PASS |
| `The result of their computation... returns are...` | 1 vector: output `are` | 0 vectors | PASS |
| `Given input [1,2,3], function returns 6.` | 1 vector | 1 vector: `[1,2,3]` -> `6` | PASS |
| `Input: [] -> Output: 0` | 0 vectors | 1 vector: `[]` -> `0` | PASS |
| ``Given `[-1,2,3]`, returns `4` `` | 1 broken vector with nulls | 1 vector: `[-1,2,3]` -> `4` | PASS |
| `Input: {"temperature": -5, "max": 0} -> Output: true` | 0 vectors | 1 vector | PASS |
| Natural-language cold-chain sentence without literals | 1 loose vector | 0 vectors | PASS, documented limitation |

## Full Demo Extraction

Spec used:

```text
# Sum List Demo
- The result of their computation must be validated before returns are processed.
- Given input [1,2,3], function returns 6.
```

Command result:

```text
Golden Demo: 1 vector(s) extracted [regex parse] -> .specify/golden-demo\test-vectors.md
Golden Demo: 1 golden template(s) created in .specify/golden-demo\golden
```

Generated vector:

```text
### Vector 1
- Criteria: Given input [1,2,3], function returns 6.
- Input: [1,2,3]
- Expected Output: 6
- Is Pure: True
- Status: pending-execution
```

The false-positive sentence did not appear in `test-vectors.md`.

## Backward Compatibility Notes

Structured sum-list examples still extract correctly. A structured cold-chain example also extracts correctly. Natural-language-only acceptance criteria may no longer be extracted by regex fallback; this is intentional and documented in README.md under accepted regex fallback formats.
