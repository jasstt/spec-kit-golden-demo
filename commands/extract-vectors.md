---
description: "Reads spec.md and plan.md for the current feature, identifies lines that contain acceptance criteria, writes them to .specify/golden-demo/test-vectors.md, and creates empty golden templates."
---

# Golden Demo — Extract Test Vectors

This command runs automatically after `/speckit.plan`. It scans the feature
specification and plan for acceptance criteria items, captures them as
test vectors, and generates empty golden example templates.

## Steps

1. Parse spec.md and plan.md.
2. Extract criteria and generate templates.

```bash
python3 - << 'EOF'
import os
import re
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

# Extract lines that look like acceptance criteria with inputs/outputs
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

for i, (line_num, text) in enumerate(criteria_lines):
    vec_id = i + 1
    input_val = "not specified"
    expected_val = "not specified"
    status = "skipped-no-example"
    
    # Extremely naive extraction for demo purposes
    # Matches patterns like: Given input [1,2,3], function returns 6
    # Matches patterns like: Given empty list [], function returns 0
    input_match = re.search(r'(?:input|list) (\[.*?\]|\w+)', text, re.IGNORECASE)
    if input_match:
        input_val = input_match.group(1)
        
    return_match = re.search(r'returns? (\[.*?\]|\w+)', text, re.IGNORECASE)
    if return_match:
        expected_val = return_match.group(1)
        
    if input_val != "not specified" and expected_val != "not specified":
        status = "pending-execution"
        pending_count += 1
        
    vectors_md += f"### Vector {vec_id}\n"
    vectors_md += f"- Source: spec.md, line {line_num}\n"
    vectors_md += f"- Criteria: {text}\n"
    vectors_md += f"- Input: {input_val}\n"
    vectors_md += f"- Expected Output: {expected_val}\n"
    vectors_md += f"- Status: {status}\n\n"
    
    # Create golden template
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

with open(test_vectors_path, "w") as f:
    f.write(vectors_md)

print(f"Golden Demo: {len(criteria_lines)} test vector(s) extracted -> {test_vectors_path}")
if pending_count > 0:
    print(f"Golden Demo: {pending_count} golden example template(s) created.")
    print("Please implement them in .specify/golden-demo/golden/ before running check-drift.")
EOF
```
