---
description: "Reads spec.md and plan.md for the current feature, identifies lines that contain acceptance criteria, writes them to .specify/golden-demo/test-vectors.md, and creates empty golden templates. Supports deterministic fuzzing for typed inputs."
---

# Golden Demo — Extract Test Vectors

This command runs automatically after `/speckit.plan`. It scans the feature
specification and plan for acceptance criteria items, captures them as
test vectors, and generates empty golden example templates.

## Steps

1. Parse spec.md and plan.md.
2. Extract criteria, apply deterministic fuzzing if applicable, and generate templates.

```bash
python3 - << 'EOF'
import os
import re
import sys
import random
from datetime import datetime

spec_dir = ".specify/golden-demo"
golden_dir = os.path.join(spec_dir, "golden")
os.makedirs(golden_dir, exist_ok=True)
test_vectors_path = os.path.join(spec_dir, "test-vectors.md")

content = ""
for filename in ["spec.md", "plan.md"]:
    if os.path.exists(filename):
        with open(filename, "r") as f:
            content += f.read() + "\n"

if not content:
    print("Golden Demo: spec.md / plan.md not found, skipping vector extraction")
    exit(0)

criteria_lines = []
for idx, line in enumerate(content.split('\n')):
    line = line.strip()
    if line.startswith('-') and 'return' in line.lower():
        criteria_lines.append((idx + 1, line.lstrip('- ')))

if not criteria_lines:
    with open(test_vectors_path, "w") as f:
        f.write(f"# Test Vectors — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n<!-- No explicitly formatted acceptance criteria detected -->\n")
    print("Golden Demo: 0 test vector(s) extracted.")
    exit(0)

vectors_md = f"# Test Vectors — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
pending_count = 0

# Deterministic Fuzzing
random.seed(42)

def generate_fuzz_inputs(type_hint):
    fuzz_inputs = []
    type_hint = type_hint.lower().replace("type:", "").strip()
    
    if "list" in type_hint or "[]" in type_hint:
        fuzz_inputs.extend([
            "[]",  # empty list
            "[null]",  # null value
            "[-1]",  # negative number / single element
            f"[{sys.maxsize}]",  # max size
            "['\\u0000', 'ñ', '🚀']",  # unicode
            str([random.randint(-1000, 1000) for _ in range(1005)])  # 1000+ items
        ])
    elif "str" in type_hint or "string" in type_hint:
        fuzz_inputs.extend([
            '""',  # empty string
            '"null"',
            '"\\u0000ñ🚀"',  # unicode
            '"A" * 1005'  # long string
        ])
    elif "int" in type_hint or "num" in type_hint:
        fuzz_inputs.extend([
            "0",
            "-1",
            str(sys.maxsize),
            str(-sys.maxsize - 1),
            "null"
        ])
    return fuzz_inputs

vector_count = 0

for i, (line_num, text) in enumerate(criteria_lines):
    vec_id = str(i + 1)
    input_val = "not specified"
    expected_val = "not specified"
    status = "skipped-no-example"
    
    input_match = re.search(r'(?:input|list|type) (type:\w+\[?\w*\]?|\[.*?\]|\w+)', text, re.IGNORECASE)
    if input_match:
        input_val = input_match.group(1)
        
    return_match = re.search(r'returns? (\[.*?\]|\w+)', text, re.IGNORECASE)
    if return_match:
        expected_val = return_match.group(1)
        
    if input_val != "not specified" and expected_val != "not specified":
        status = "pending-execution"
        pending_count += 1
        
    vector_count += 1
    vectors_md += f"### Vector {vec_id}\n"
    vectors_md += f"- Source: spec.md, line {line_num}\n"
    vectors_md += f"- Criteria: {text}\n"
    vectors_md += f"- Input: {input_val}\n"
    vectors_md += f"- Expected Output: {expected_val}\n"
    vectors_md += f"- Status: {status}\n\n"
    
    if status == "pending-execution":
        template_path = os.path.join(golden_dir, f"vector_{vec_id}_golden.py")
        if not os.path.exists(template_path):
            with open(template_path, "w") as f:
                f.write(f"# Golden Example for Vector {vec_id}\n")
                f.write(f"# Criteria: {text}\n\n")
                f.write(f"def execute(input_data):\n")
                f.write(f"    \"\"\"\n")
                f.write(f"    Expected Output: {expected_val}\n")
                f.write(f"    \"\"\"\n")
                f.write(f"    # TODO: Implement this pure function\n")
                f.write(f"    pass\n")

        # Fuzzing Generation
        if "type:" in input_val.lower():
            fuzz_inputs = generate_fuzz_inputs(input_val)
            for f_idx, f_in in enumerate(fuzz_inputs):
                f_id = f"{vec_id}.{f_idx + 1}"
                vector_count += 1
                vectors_md += f"### Vector {f_id}\n"
                vectors_md += f"- Source: fuzzer, seed: 42 (based on vector {vec_id})\n"
                vectors_md += f"- Criteria: Auto-fuzzed edge case for {input_val}\n"
                vectors_md += f"- Input: {f_in}\n"
                vectors_md += f"- Expected Output: dynamic (must match golden execution)\n"
                vectors_md += f"- Status: pending-execution\n\n"

with open(test_vectors_path, "w") as f:
    f.write(vectors_md)

print(f"Golden Demo: {vector_count} test vector(s) extracted/generated -> {test_vectors_path}")
if pending_count > 0:
    print(f"Golden Demo: {pending_count} golden example template(s) created.")
    print("Please implement them in .specify/golden-demo/golden/ or use /speckit.auto-golden before running check-drift.")
EOF
```
