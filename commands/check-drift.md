---
description: "Executes golden examples against real implementations. Supports mock context for side-effecting code. Uses semantic comparison (numeric tolerance, type coercion, partial list scoring)."
---

# Golden Demo — Behavioral Drift Check

This command runs automatically after `/speckit.implement`.

```bash
python3 - << 'EOF'
import os
import re
import sys
import importlib.util
import ast
import json
import subprocess
from datetime import datetime

golden_demo_mode = os.environ.get("GOLDEN_DEMO_MODE", "warn").lower()

spec_dir = ".specify/golden-demo"
golden_dir = os.path.join(spec_dir, "golden")
mocks_dir = os.path.join(spec_dir, "mocks")
test_vectors_path = os.path.join(spec_dir, "test-vectors.md")
report_path = os.path.join(spec_dir, "drift-report.md")
config_path = os.path.join(spec_dir, "config.json")

config = {
    "real_cmd": "python sum_list.py",
    "input_method": "auto",
    "input_size_threshold_bytes": 4096
}
if os.path.exists(config_path):
    with open(config_path, "r") as f:
        try:
            config.update(json.load(f))
        except Exception as e:
            print(f"Warning: Could not parse config.json ({e})")
else:
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

if not os.path.exists(test_vectors_path):
    print("Golden Demo: no test vectors found. Run /speckit.plan first.")
    exit(0)

with open(test_vectors_path, "r", encoding="utf-8") as f:
    content = f.read()

# ─── PARSE VECTORS ────────────────────────────────────────────────────────────

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
    elif line.startswith("- Is Pure: "):
        current_vec["is_pure"] = line.replace("- Is Pure: ", "").strip().lower() != "false"
    elif line.startswith("- Side Effects: "):
        current_vec["side_effects"] = line.replace("- Side Effects: ", "").strip()
if current_vec:
    vectors.append(current_vec)

if not vectors:
    print("Golden Demo: test-vectors.md contains no vectors.")
    exit(0)

# ─── MODULE LOADER ────────────────────────────────────────────────────────────

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

# ─── SEMANTIC COMPARE ─────────────────────────────────────────────────────────

def compare(golden, real):
    """
    Returns (drift_score, match_type).
    drift_score: 0.0 = identical, 1.0 = completely different, 0.x = partial
    match_type: exact | numeric_tolerance | type_coercion | partial_list | length_mismatch | mismatch
    """
    # 1. Exact match
    if golden == real:
        return 0.0, "exact"

    # 2. Numeric tolerance (float vs int, rounding errors)
    try:
        if abs(float(str(golden)) - float(str(real))) < 1e-9:
            return 0.0, "numeric_tolerance"
    except (TypeError, ValueError):
        pass

    # 3. Type coercion (str "6" vs int 6)
    try:
        if str(golden) == str(real):
            return 0.0, "type_coercion"
    except Exception:
        pass

    # 4. List partial comparison
    if isinstance(golden, list) and isinstance(real, list):
        if len(golden) == 0 and len(real) == 0:
            return 0.0, "exact"
        if len(golden) != len(real):
            return 1.0, "length_mismatch"
        mismatches = sum(1 for a, b in zip(golden, real) if str(a) != str(b))
        score = round(mismatches / len(golden), 2)
        return score, "partial_list"

    # 5. Dict partial comparison
    if isinstance(golden, dict) and isinstance(real, dict):
        all_keys = set(golden) | set(real)
        if not all_keys:
            return 0.0, "exact"
        mismatches = sum(1 for k in all_keys if str(golden.get(k)) != str(real.get(k)))
        score = round(mismatches / len(all_keys), 2)
        return score, "partial_dict"

    return 1.0, "mismatch"

# ─── SUBPROCESS RUNNER ────────────────────────────────────────────────────────

def run_real(json_input, context=None):
    real_cmd = config["real_cmd"]
    input_method = config.get("input_method", "auto")
    if input_method == "auto":
        input_method = "stdin" if len(json_input.encode()) > config.get("input_size_threshold_bytes", 4096) else "arg"

    # Inject context as env var if present
    env = os.environ.copy()
    if context:
        env["GOLDEN_DEMO_CONTEXT"] = json.dumps(context)

    if input_method == "arg":
        cmd = real_cmd.replace("{input}", json_input) if "{input}" in real_cmd else f"{real_cmd} '{json_input}'"
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True, env=env)
    else:
        cmd = real_cmd.replace(" '{input}'", "").replace(' "{input}"', "").replace(" {input}", "")
        proc = subprocess.run(cmd, shell=True, input=json_input, capture_output=True, text=True, check=True, env=env)

    raw = proc.stdout.strip()
    try:
        return ast.literal_eval(raw)
    except Exception:
        try:
            return json.loads(raw)
        except Exception:
            return raw

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

results = []
skipped = []
total_executed = 0
pass_count = 0
fail_count = 0
error_count = 0

for vec in vectors:
    if vec.get("status") != "pending-execution":
        skipped.append({"id": vec['id'], "reason": "Not pending"})
        continue

    # Find golden
    golden_path = os.path.join(golden_dir, f"vector_{vec['id']}_golden.py")
    if not os.path.exists(golden_path) and "." in vec['id']:
        parent_id = vec['id'].split('.')[0]
        golden_path = os.path.join(golden_dir, f"vector_{parent_id}_golden.py")
    if not os.path.exists(golden_path):
        skipped.append({"id": vec['id'], "reason": "Golden template missing or not implemented"})
        continue

    # Load golden
    try:
        golden_mod = load_module(f"golden_{vec['id']}", golden_path)
        if not hasattr(golden_mod, 'execute'):
            raise AttributeError("Missing execute function")
    except Exception as e:
        skipped.append({"id": vec['id'], "reason": f"Golden load error: {e}"})
        continue

    # Load mock if side-effecting
    is_pure = vec.get("is_pure", True)
    mock_mod = None
    context = None
    mock_path = os.path.join(mocks_dir, f"vector_{vec['id']}_mock.py")
    if not is_pure and os.path.exists(mock_path):
        try:
            mock_mod = load_module(f"mock_{vec['id']}", mock_path)
            if hasattr(mock_mod, 'setup'):
                context = mock_mod.setup()
        except Exception as e:
            skipped.append({"id": vec['id'], "reason": f"Mock load error: {e}"})
            continue
    elif not is_pure:
        skipped.append({"id": vec['id'], "reason": "Side-effecting vector but no mock file found"})
        continue

    total_executed += 1
    input_str = vec.get("input", "not specified")
    try:
        input_data = ast.literal_eval(input_str)
    except Exception:
        input_data = input_str

    try:
        # Execute golden
        if context is not None:
            try:
                golden_out = golden_mod.execute(input_data, context)
            except TypeError:
                golden_out = golden_mod.execute(input_data)
        else:
            golden_out = golden_mod.execute(input_data)

        # Execute real
        json_input = json.dumps(input_data)
        real_out = run_real(json_input, context)

        drift, match_type = compare(golden_out, real_out)
        status = "PASS" if drift == 0.0 else "FAIL"
        if status == "PASS":
            pass_count += 1
        else:
            fail_count += 1

        results.append({
            "id": vec["id"],
            "criteria": vec.get("criteria", ""),
            "status": status,
            "input": input_str,
            "golden_out": golden_out,
            "real_out": real_out,
            "drift": drift,
            "match_type": match_type,
            "notes": ""
        })

    except subprocess.CalledProcessError as e:
        error_count += 1
        results.append({"id": vec["id"], "criteria": vec.get("criteria",""), "status": "ERROR",
                        "input": input_str, "golden_out": "N/A", "real_out": "N/A",
                        "drift": "null", "match_type": "error",
                        "notes": f"Process exited {e.returncode}: {e.stderr[:200]}"})
    except Exception as e:
        error_count += 1
        results.append({"id": vec["id"], "criteria": vec.get("criteria",""), "status": "ERROR",
                        "input": input_str, "golden_out": "N/A", "real_out": "N/A",
                        "drift": "null", "match_type": "error", "notes": str(e)[:200]})
    finally:
        if mock_mod and hasattr(mock_mod, 'teardown') and context is not None:
            try:
                mock_mod.teardown(context)
            except Exception:
                pass

drift_score = round(fail_count / total_executed, 2) if total_executed > 0 else 0.0

# ─── REPORT ───────────────────────────────────────────────────────────────────

report = f"# Golden Demo Drift Report\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
if golden_demo_mode == "warn":
    report += "MODE: warn-only, build not blocked\n\n"

report += "## Summary\n"
report += f"- Total vectors: {len(vectors)}\n"
report += f"- Executed: {total_executed}\n"
report += f"- PASS: {pass_count}\n"
report += f"- FAIL: {fail_count}\n"
report += f"- ERROR: {error_count}\n"
report += f"- Skipped: {len(skipped)}\n\n"
report += f"## Overall Drift Score: {drift_score:.2f}\n\n"
report += "## Results\n\n"

for res in results:
    report += f"### Vector {res['id']} -- {res['criteria']}\n"
    report += f"- Status: {res['status']}\n"
    report += f"- Input: {res['input']}\n"
    report += f"- Golden Output: {res['golden_out']}\n"
    report += f"- Real Output: {res['real_out']}\n"
    report += f"- Drift: {res['drift']} ({res['match_type']})\n"
    if res['notes']:
        report += f"- Notes: {res['notes']}\n"
    report += "\n"

report += "## Skipped Vectors\n"
for s in skipped:
    report += f"- Vector {s['id']}: {s['reason']}\n"

with open(report_path, "w", encoding="utf-8") as f:
    f.write(report)

print(f"\nGolden Demo v0.4.0")
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
        print("[X] Behavioral drift detected. Strict mode enabled. FAILING BUILD.")
        sys.exit(1)
    else:
        print("[!] Behavioral drift detected. Review before merging. (Warn-only mode)")
        sys.exit(0)
else:
    print("[OK] No drift detected. Implementation matches spec.")
    sys.exit(0)
EOF
```
