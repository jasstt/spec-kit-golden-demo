---
description: "Reads .specify/golden-demo/test-vectors.md and executes both golden and real implementations against the inputs, calculating deterministic drift score."
---

# Golden Demo — Behavioral Drift Check

This command runs automatically after `/speckit.implement`. It executes implemented
golden templates against the real implementation to detect behavioral drift.

## Steps

1. Run behavioral execution pipeline.

```bash
python3 - << 'EOF'
import os
import re
import sys
import time
import importlib.util
import ast
import json
import subprocess
from datetime import datetime

# Read Warn/Strict Mode
golden_demo_mode = os.environ.get("GOLDEN_DEMO_MODE", "warn").lower()

spec_dir = ".specify/golden-demo"
golden_dir = os.path.join(spec_dir, "golden")
test_vectors_path = os.path.join(spec_dir, "test-vectors.md")
report_path = os.path.join(spec_dir, "drift-report.md")
config_path = os.path.join(spec_dir, "config.json")

# Default Config
config = {
    "real_cmd": "python sum_list.py",
    "input_method": "auto",
    "input_size_threshold_bytes": 4096
}

if os.path.exists(config_path):
    with open(config_path, "r") as f:
        try:
            user_config = json.load(f)
            config.update(user_config)
        except Exception as e:
            print(f"Warning: Could not parse config.json ({e})")
else:
    # Auto-generate default config if missing
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

if not os.path.exists(test_vectors_path):
    print("Golden Demo: no test vectors found. Run /speckit.plan first.")
    exit(0)

with open(test_vectors_path, "r") as f:
    content = f.read()

vectors = []
current_vec = {}
for line in content.split('\n'):
    if line.startswith("### Vector "):
        if current_vec:
            vectors.append(current_vec)
        current_vec = {"id": line.replace("### Vector ", "").strip()}
    elif line.startswith("- Source: "):
        current_vec["source"] = line.replace("- Source: ", "").strip()
    elif line.startswith("- Criteria: "):
        current_vec["criteria"] = line.replace("- Criteria: ", "").strip()
    elif line.startswith("- Input: "):
        current_vec["input"] = line.replace("- Input: ", "").strip()
    elif line.startswith("- Expected Output: "):
        current_vec["expected"] = line.replace("- Expected Output: ", "").strip()
    elif line.startswith("- Status: "):
        current_vec["status"] = line.replace("- Status: ", "").strip()
if current_vec:
    vectors.append(current_vec)

if not vectors:
    print("Golden Demo: test-vectors.md contains no vectors.")
    exit(0)

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

results = []
skipped = []
total_executed = 0
pass_count = 0
fail_count = 0
error_count = 0

for vec in vectors:
    if vec.get("status") != "pending-execution":
        skipped.append({"id": vec['id'], "reason": "No explicit example / Not pending"})
        continue

    golden_path = os.path.join(golden_dir, f"vector_{vec['id']}_golden.py")
    if not os.path.exists(golden_path) and "." in vec['id']:
        parent_id = vec['id'].split('.')[0]
        golden_path = os.path.join(golden_dir, f"vector_{parent_id}_golden.py")
        
    if not os.path.exists(golden_path):
        skipped.append({"id": vec['id'], "reason": "Golden template missing"})
        continue

    # Load golden
    try:
        golden_mod = load_module(f"golden_{vec['id']}", golden_path)
        if not hasattr(golden_mod, 'execute'):
             raise AttributeError("Missing execute function")
    except Exception as e:
        skipped.append({"id": vec['id'], "reason": f"Golden implementation error: {e}"})
        continue

    # Execute
    total_executed += 1
    input_str = vec["input"]
    
    try:
        input_data = ast.literal_eval(input_str)
    except Exception:
        input_data = input_str
        
    # Serialize input to pass to CLI or stdin
    json_input = json.dumps(input_data)
    input_method = config.get("input_method", "auto")
    if input_method == "auto":
        if len(json_input.encode('utf-8')) > config.get("input_size_threshold_bytes", 4096):
            input_method = "stdin"
        else:
            input_method = "arg"

    try:
        # Golden output
        golden_out = golden_mod.execute(input_data)
        
        # Real Output (Cross-language execution via subprocess)
        real_cmd = config["real_cmd"]
        
        if input_method == "arg":
            # Pass as argument if {input} template exists, else append
            if "{input}" in real_cmd:
                cmd = real_cmd.replace("{input}", json_input)
            else:
                cmd = f"{real_cmd} '{json_input}'"
            
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
            real_out_raw = proc.stdout.strip()
        else: # stdin
            # Remove {input} placeholder if present for stdin mode
            cmd = real_cmd.replace(" '{input}'", "").replace(' "{input}"', "").replace(" {input}", "")
            proc = subprocess.run(cmd, shell=True, input=json_input, capture_output=True, text=True, check=True)
            real_out_raw = proc.stdout.strip()
            
        # Try to parse real_out as python object for strict equality comparison
        try:
            real_out = ast.literal_eval(real_out_raw)
        except Exception:
            try:
                real_out = json.loads(real_out_raw)
            except Exception:
                real_out = real_out_raw
        
        drift = 0.0 if str(golden_out) == str(real_out) else 1.0
        status = "PASS" if drift == 0.0 else "FAIL"
        
        if status == "PASS":
            pass_count += 1
        else:
            fail_count += 1
            
        results.append({
            "id": vec["id"],
            "criteria": vec["criteria"],
            "status": status,
            "input": input_str,
            "golden_out": golden_out,
            "real_out": real_out,
            "drift": drift,
            "notes": ""
        })
    except subprocess.CalledProcessError as e:
        error_count += 1
        results.append({
            "id": vec["id"],
            "criteria": vec["criteria"],
            "status": "ERROR",
            "input": input_str,
            "golden_out": "N/A",
            "real_out": "N/A",
            "drift": "null",
            "notes": f"Process exited with {e.returncode}: {e.stderr}"
        })
    except Exception as e:
        error_count += 1
        results.append({
            "id": vec["id"],
            "criteria": vec["criteria"],
            "status": "ERROR",
            "input": input_str,
            "golden_out": "N/A",
            "real_out": "N/A",
            "drift": "null",
            "notes": str(e)
        })

drift_score = (fail_count / total_executed) if total_executed > 0 else 0.0

report_content = f"# Golden Demo Drift Report\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
if golden_demo_mode == "warn":
    report_content += "⚠️ **MODE: warn-only, build not blocked**\n\n"

report_content += "## Summary\n"
report_content += f"- Total vectors: {len(vectors)}\n"
report_content += f"- Executed: {total_executed}\n"
report_content += f"- PASS: {pass_count} (drift: 0.0)\n"
report_content += f"- FAIL: {fail_count} (drift: 1.0)\n"
report_content += f"- ERROR: {error_count}\n"
report_content += f"- Skipped: {len(skipped)}\n\n"
report_content += f"## Overall Drift Score: {drift_score:.2f}\n\n"
report_content += "## Results\n\n"

for res in results:
    report_content += f"### Vector {res['id']} — {res['criteria']}\n"
    report_content += f"- Status: {res['status']}\n"
    report_content += f"- Input: {res['input']}\n"
    report_content += f"- Golden Output: {res['golden_out']}\n"
    report_content += f"- Real Output: {res['real_out']}\n"
    report_content += f"- Drift: {res['drift']}\n"
    if res['notes']:
        report_content += f"- Notes: {res['notes']}\n"
    report_content += "\n"

report_content += "## Skipped Vectors\n"
for s in skipped:
    report_content += f"- Vector {s['id']}: {s['reason']}\n"

with open(report_path, "w", encoding="utf-8") as f:
    f.write(report_content)

print("\nGolden Demo v0.3.0")
print("-" * 34)
if golden_demo_mode == "warn":
    print(f"PASS: {pass_count}  FAIL: {fail_count}  ERROR: {error_count}  (WARN ONLY)")
else:
    print(f"PASS: {pass_count}  FAIL: {fail_count}  ERROR: {error_count}")
print(f"Overall Drift Score: {drift_score:.2f}")
print(f"Report: {report_path}")
print("-" * 34 + "\n")

if drift_score > 0 or error_count > 0:
    if golden_demo_mode == "strict":
        print("[X] Behavioral drift detected. Strict mode enabled. FAIILING BUILD.")
        sys.exit(1)
    else:
        print("[!] Behavioral drift detected. Review before merging. (Warn-only mode)")
        sys.exit(0)
else:
    print("[OK] No drift detected. Implementation matches spec.")
    sys.exit(0)
EOF
```
