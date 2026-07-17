---
description: "Reads spec.md and plan.md, extracts acceptance criteria via LLM (Gemini/OpenAI) with regex fallback, writes test-vectors.md, and creates empty golden + mock templates."
---

# Golden Demo — Extract Test Vectors

This command runs automatically after `/speckit.plan`. It uses a hybrid approach:
LLM parses natural language specs into structured vectors, regex is the fallback.

## Steps

1. Parse spec.md and plan.md.
2. Try LLM extraction → fallback to regex if unavailable.
3. Generate templates and fuzz vectors.

```bash
python3 - << 'EOF'
import os
import re
import sys
import json
import random
import urllib.request
from datetime import datetime

spec_dir = ".specify/golden-demo"
golden_dir = os.path.join(spec_dir, "golden")
mocks_dir = os.path.join(spec_dir, "mocks")
os.makedirs(golden_dir, exist_ok=True)
os.makedirs(mocks_dir, exist_ok=True)
test_vectors_path = os.path.join(spec_dir, "test-vectors.md")

content = ""
for filename in ["spec.md", "plan.md"]:
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            content += f.read() + "\n"

if not content.strip():
    print("Golden Demo: spec.md / plan.md not found, skipping vector extraction")
    exit(0)

# ─── LLM PARSE ────────────────────────────────────────────────────────────────

def call_llm_parse(spec_text):
    """Ask LLM to extract structured vectors from natural language spec."""
    openai_key = os.environ.get("OPENAI_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not openai_key and not gemini_key:
        return None

    prompt = (
        "You are a test vector extractor. Given a software specification, "
        "extract all testable acceptance criteria into a JSON array.\n\n"
        "Rules:\n"
        "- Only extract criteria that describe input→output or state→behavior relationships.\n"
        "- For each criterion, determine if it is a pure function (no DB/HTTP/file side effects).\n"
        "- If input or output cannot be inferred, set them to null.\n"
        "- Respond ONLY with a valid JSON array, no explanations.\n\n"
        "Output format:\n"
        '[{"criteria": "original text", "input_type": "list[int]|str|int|dict|unknown", '
        '"example_input": "[1,2,3]" or null, "expected_output": "6" or null, '
        '"is_pure": true/false, "side_effects": []}]\n\n'
        f"Specification:\n{spec_text}"
    )

    try:
        if gemini_key:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            data = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.0}}
            req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read())
                raw = res["candidates"][0]["content"]["parts"][0]["text"]
        else:
            url = "https://api.openai.com/v1/chat/completions"
            data = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.0}
            req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {openai_key}"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read())
                raw = res["choices"][0]["message"]["content"]

        # Strip markdown code blocks if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip().rstrip("```").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"Golden Demo: LLM parse failed ({e}), falling back to regex.")
        return None

# ─── REGEX FALLBACK ───────────────────────────────────────────────────────────

def regex_parse(text):
    criteria_lines = []
    for idx, line in enumerate(text.split('\n')):
        line = line.strip()
        if line.startswith('-') and 'return' in line.lower():
            criteria_lines.append((idx + 1, line.lstrip('- ')))
    results = []
    for line_num, text in criteria_lines:
        input_val = None
        expected_val = None
        input_match = re.search(r'(?:input|list|type) (type:\w+\[?\w*\]?|\[.*?\]|\w+)', text, re.IGNORECASE)
        if input_match:
            input_val = input_match.group(1)
        return_match = re.search(r'returns? (\[.*?\]|\w+)', text, re.IGNORECASE)
        if return_match:
            expected_val = return_match.group(1)
        results.append({
            "criteria": text,
            "input_type": "unknown",
            "example_input": input_val,
            "expected_output": expected_val,
            "is_pure": True,
            "side_effects": []
        })
    return results

# ─── FUZZING ──────────────────────────────────────────────────────────────────

random.seed(42)

def generate_fuzz_inputs(type_hint):
    fuzz_inputs = []
    th = (type_hint or "").lower()
    if "list" in th or "[]" in th:
        fuzz_inputs.extend([
            "[]",
            "[null]",
            "[-1]",
            f"[{sys.maxsize}]",
            str([random.randint(-1000, 1000) for _ in range(1005)])
        ])
    elif "str" in th or "string" in th:
        fuzz_inputs.extend(['""', '"null"', '"A" * 1005'])
    elif "int" in th or "num" in th:
        fuzz_inputs.extend(["0", "-1", str(sys.maxsize), str(-sys.maxsize - 1)])
    return fuzz_inputs

# ─── TEMPLATE WRITERS ─────────────────────────────────────────────────────────

def write_golden_template(vec_id, criteria, expected_val, has_side_effects):
    template_path = os.path.join(golden_dir, f"vector_{vec_id}_golden.py")
    if not os.path.exists(template_path):
        ctx_param = ", context=None" if has_side_effects else ""
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(f"# Golden Example for Vector {vec_id}\n")
            f.write(f"# Criteria: {criteria}\n\n")
            f.write(f"def execute(input_data{ctx_param}):\n")
            f.write(f'    """\n')
            f.write(f"    Expected Output: {expected_val or 'not specified'}\n")
            f.write(f'    """\n')
            f.write(f"    # TODO: Implement this pure function\n")
            f.write(f"    pass\n")

def write_mock_template(vec_id, criteria, side_effects):
    mock_path = os.path.join(mocks_dir, f"vector_{vec_id}_mock.py")
    if not os.path.exists(mock_path):
        with open(mock_path, "w", encoding="utf-8") as f:
            f.write(f"# Mock for Vector {vec_id}\n")
            f.write(f"# Criteria: {criteria}\n")
            f.write(f"# Side effects: {', '.join(side_effects) or 'none'}\n\n")
            f.write("def setup():\n")
            f.write('    """\n')
            f.write("    Run before the test. Return a context dict.\n")
            f.write("    Example: return {'db': {}, 'http_responses': {}}\n")
            f.write('    """\n')
            f.write("    # TODO: Set up your test context\n")
            f.write("    return {}\n\n")
            f.write("def teardown(context):\n")
            f.write('    """\n')
            f.write("    Run after the test. Clean up resources.\n")
            f.write('    """\n')
            f.write("    pass\n")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

parse_method = "regex"
vectors_raw = call_llm_parse(content)
if vectors_raw and isinstance(vectors_raw, list) and len(vectors_raw) > 0:
    parse_method = "llm"
else:
    vectors_raw = regex_parse(content)

if not vectors_raw:
    with open(test_vectors_path, "w", encoding="utf-8") as f:
        f.write(f"# Test Vectors — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("<!-- No acceptance criteria detected -->\n")
    print("Golden Demo: 0 test vector(s) extracted.")
    exit(0)

vectors_md = f"# Test Vectors — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
vectors_md += f"<!-- parse_method: {parse_method} -->\n\n"

pending_count = 0
mock_count = 0
vector_count = 0

for i, vec in enumerate(vectors_raw):
    vec_id = str(i + 1)
    criteria = vec.get("criteria", "")
    input_val = vec.get("example_input") or "not specified"
    expected_val = vec.get("expected_output") or "not specified"
    is_pure = vec.get("is_pure", True)
    side_effects = vec.get("side_effects", [])
    input_type = vec.get("input_type", "unknown")
    has_side_effects = not is_pure or len(side_effects) > 0

    status = "pending-execution" if (input_val != "not specified" and expected_val != "not specified") else "skipped-no-example"
    if status == "pending-execution":
        pending_count += 1

    vector_count += 1
    vectors_md += f"### Vector {vec_id}\n"
    vectors_md += f"- Source: spec.md ({parse_method} parse)\n"
    vectors_md += f"- Criteria: {criteria}\n"
    vectors_md += f"- Input: {input_val}\n"
    vectors_md += f"- Expected Output: {expected_val}\n"
    vectors_md += f"- Is Pure: {is_pure}\n"
    if side_effects:
        vectors_md += f"- Side Effects: {', '.join(side_effects)}\n"
    vectors_md += f"- Status: {status}\n\n"

    if status == "pending-execution":
        write_golden_template(vec_id, criteria, expected_val, has_side_effects)
        if has_side_effects:
            write_mock_template(vec_id, criteria, side_effects)
            mock_count += 1

        # Fuzz only pure typed inputs
        if is_pure and "type:" in str(input_val).lower():
            fuzz_inputs = generate_fuzz_inputs(input_type)
            for f_idx, f_in in enumerate(fuzz_inputs):
                f_id = f"{vec_id}.{f_idx + 1}"
                vector_count += 1
                vectors_md += f"### Vector {f_id}\n"
                vectors_md += f"- Source: fuzzer, seed: 42 (based on vector {vec_id})\n"
                vectors_md += f"- Criteria: Auto-fuzzed edge case for {input_type}\n"
                vectors_md += f"- Input: {f_in}\n"
                vectors_md += f"- Expected Output: dynamic (must match golden execution)\n"
                vectors_md += f"- Is Pure: True\n"
                vectors_md += f"- Status: pending-execution\n\n"

with open(test_vectors_path, "w", encoding="utf-8") as f:
    f.write(vectors_md)

print(f"Golden Demo: {vector_count} vector(s) extracted [{parse_method} parse] -> {test_vectors_path}")
if pending_count > 0:
    print(f"Golden Demo: {pending_count} golden template(s) created in {golden_dir}")
if mock_count > 0:
    print(f"Golden Demo: {mock_count} mock template(s) created in {mocks_dir}")
    print("Note: Implement mock setup/teardown before running check-drift on side-effecting vectors.")
EOF
```
