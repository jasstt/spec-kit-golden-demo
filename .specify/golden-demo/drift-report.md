# Golden Demo Drift Report
Generated: 2026-06-27 19:35:51

## Summary
- Total vectors: 3
- Executed: 3
- PASS: 2 (drift: 0.0)
- FAIL: 1 (drift: 1.0)
- ERROR: 0
- Skipped: 0

## Overall Drift Score: 0.33

## Results

### Vector 1 — Given input [1,2,3], function returns 6
- Status: PASS
- Input: [1,2,3]
- Golden Output: 6
- Real Output: 6
- Drift: 0.0

### Vector 2 — Given empty list [], function returns 0
- Status: FAIL
- Input: []
- Golden Output: 0
- Real Output: 1
- Drift: 1.0

### Vector 3 — Given input [5], function returns 5
- Status: PASS
- Input: [5]
- Golden Output: 5
- Real Output: 5
- Drift: 0.0

## Skipped Vectors
