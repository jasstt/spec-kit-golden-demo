# GATED Snapshot Bug Capture Test

## Scope

This test verifies that `snapshot_mode: "gated"` does not silently capture buggy first-run behavior, while also proving the risk when a human explicitly accepts a bad baseline.

There is no `snapshot_mode: "auto"` in this design.

## Buggy Real Implementation

The real implementation intentionally contains the empty-list bug:

```python
import json, sys

values = json.loads(sys.stdin.read() or "[]")
if values == []:
    print(1)
else:
    print(sum(values))
```

The vector expects the mathematically correct behavior:

```text
Input: []
Expected Output: 0
```

The golden file starts as an empty template:

```python
def execute(input_data):
    # TODO: Implement this pure function
    pass
```

Config:

```json
{
  "real_cmd": "python buggy_sum.py",
  "input_method": "stdin",
  "snapshot_mode": "gated"
}
```

## Rejection Path

When the first run produced the buggy output, the reviewer rejected it:

```text
No golden reference exists. Real code produced: 1. Accept this as golden truth? [y/N]: n
```

Result:

```text
Golden Demo v0.4.2
PASS: 0  FAIL: 0  ERROR: 0  UNSUPPORTED: 0  SNAPSHOT_PENDING: 1
Drift Score: 0.00
[!] Snapshot pending human review. No golden file was written without approval.
```

Verification:

```text
golden/vector_1_golden.py still contains:
    # TODO: Implement this pure function
    pass

golden/vector_1_golden.py does not contain:
    return 1
```

This proves the bug was not captured as golden truth after a rejection/default `N`.

## Acceptance Path

In a separate run, the reviewer explicitly accepted the buggy current behavior:

```text
No golden reference exists. Real code produced: 1. Accept this as golden truth? [y/N]: y
```

Result:

```text
Golden Demo v0.4.2
PASS: 1  FAIL: 0  ERROR: 0  UNSUPPORTED: 0  SNAPSHOT_PENDING: 0
Drift Score: 0.00
[OK] No drift detected.
```

The generated golden file became:

```python
# Golden Example for Vector 1
# Criteria: sum list returns the sum of all numbers
# Snapshot captured from real implementation after human approval.
# WARNING: this captures current behavior, not necessarily correct behavior.

def execute(input_data):
    return 1
```

This proves the documented risk: if a reviewer accepts buggy current behavior, the bug becomes the accepted baseline. README.md warns about this before use:

```text
Snapshot mode captures CURRENT behavior, not CORRECT behavior.
```
