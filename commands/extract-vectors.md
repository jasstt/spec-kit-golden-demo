---
description: "Reads spec.md and plan.md, extracts acceptance criteria via LLM (Gemini/OpenAI) with regex fallback, writes test-vectors.md, and creates golden + fixture scaffold templates for sandboxed side-effect testing."
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

spec_dir     = ".specify/golden-demo"
golden_dir   = os.path.join(spec_dir, "golden")
fixtures_dir = os.path.join(spec_dir, "fixtures")
os.makedirs(golden_dir, exist_ok=True)
os.makedirs(fixtures_dir, exist_ok=True)
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
    literal = r"(?:`[^`\n]+`|\[[^\]\n]*\]|\"[^\"\n]*\"|'[^'\n]*'|-?\d+(?:\.\d+)?|\{[^}\n]*\}|\b(?:true|false|null|None|True|False)\b)"
    patterns = [
        # Given `[1,2,3]`, returns `6`
        re.compile(rf"\bgiven\s+(?P<input>{literal})\s*,?\s*(?:function\s+)?returns?\s+(?P<output>{literal})", re.IGNORECASE),
        # Given input [1,2,3], function returns 6
        re.compile(rf"\bgiven\s+input\s+(?P<input>{literal}).*?\b(?:function\s+)?returns?\s+(?P<output>{literal})", re.IGNORECASE),
        # Input: [1,2,3] -> Output: 6
        re.compile(rf"\binput\s*:\s*(?P<input>{literal})\s*(?:->|=>|→|,|;)\s*output\s*:\s*(?P<output>{literal})", re.IGNORECASE),
        # Input [1,2,3] returns 6
        re.compile(rf"\binput\s+(?P<input>{literal}).*?\breturns?\s+(?P<output>{literal})", re.IGNORECASE),
    ]

    def clean_literal(value):
        value = value.strip()
        if len(value) >= 2 and value[0] == "`" and value[-1] == "`":
            return value[1:-1].strip()
        return value

    def infer_input_type(value):
        stripped = value.strip()
        if stripped.startswith("["):
            return "list"
        if stripped.startswith("{"):
            return "dict"
        if stripped.startswith(("\"", "'")):
            return "str"
        if re.fullmatch(r"-?\d+", stripped):
            return "int"
        if re.fullmatch(r"-?\d+\.\d+", stripped):
            return "float"
        if stripped.lower() in {"true", "false"}:
            return "bool"
        if stripped.lower() in {"null", "none"}:
            return "null"
        return "unknown"

    results = []
    for idx, raw_line in enumerate(text.split('\n')):
        line = raw_line.strip()
        if not line:
            continue
        candidate = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line)
        match = None
        for pattern in patterns:
            match = pattern.search(candidate)
            if match:
                break
        if not match:
            continue
        input_val = clean_literal(match.group("input"))
        expected_val = clean_literal(match.group("output"))
        results.append({
            "criteria": candidate,
            "input_type": infer_input_type(input_val),
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

def write_golden_template(vec_id, criteria, expected_val):
    template_path = os.path.join(golden_dir, f"vector_{vec_id}_golden.py")
    if not os.path.exists(template_path):
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(f"# Golden Example for Vector {vec_id}\n")
            f.write(f"# Criteria: {criteria}\n\n")
            f.write(f"def execute(input_data):\n")
            f.write(f'    """\n')
            f.write(f"    Expected Output: {expected_val or 'not specified'}\n")
            f.write(f'    """\n')
            f.write(f"    # TODO: Implement this pure function\n")
            f.write(f"    pass\n")

def write_fixture_scaffold(vec_id, criteria, side_effects):
    """Create fixture directory with appropriate template files for the sandbox type."""
    fixture_dir = os.path.join(fixtures_dir, f"vector_{vec_id}")
    os.makedirs(fixture_dir, exist_ok=True)
    readme_path = os.path.join(fixture_dir, "README.md")

    effect = side_effects[0] if side_effects else None

    if effect == "filesystem":
        os.makedirs(os.path.join(fixture_dir, "fs"), exist_ok=True)
        os.makedirs(os.path.join(fixture_dir, "fs_expected"), exist_ok=True)
        if not os.path.exists(readme_path):
            with open(readme_path, "w") as f:
                f.write(f"# Fixture: Vector {vec_id} (filesystem)\n\n")
                f.write(f"Criteria: {criteria}\n\n")
                f.write("## Setup\n")
                f.write("Place seed files in `fs/`. These will be copied into a tempdir before the real command runs.\n\n")
                f.write("## Expected State\n")
                f.write("Place expected output files in `fs_expected/`. Golden Demo compares these against the tempdir after execution.\n\n")
                f.write("## Real Command\n")
                f.write("Your `real_cmd` runs with the **project cwd unchanged**.\n")
                f.write("Golden Demo injects `GOLDEN_DEMO_FS_ROOT=/path/to/tempdir` as an env var.\n")
                f.write("Your code must read this env var to locate its working directory. Example:\n\n")
                f.write("```python\n")
                f.write("import os\n")
                f.write("fs_root = os.environ.get('GOLDEN_DEMO_FS_ROOT', '.')\n")
                f.write("input_path = os.path.join(fs_root, 'input.txt')\n")
                f.write("```\n\n")
                f.write("```js\n")
                f.write("const fsRoot = process.env.GOLDEN_DEMO_FS_ROOT || '.';\n")
                f.write("const inputPath = path.join(fsRoot, 'input.txt');\n")
                f.write("```\n")


    elif effect == "http":
        if not os.path.exists(os.path.join(fixture_dir, "http_routes.json")):
            with open(os.path.join(fixture_dir, "http_routes.json"), "w") as f:
                json.dump([
                    {"method": "GET", "host": "api.example.com", "path": "/users", "status": 200, "response": [{"id": 1, "name": "Ada"}]},
                    {"method": "POST", "host": "api.example.com", "path": "/users", "status": 201, "response": {"created": True}}
                ], f, indent=2)
        if not os.path.exists(os.path.join(fixture_dir, "http_expected_calls.json")):
            with open(os.path.join(fixture_dir, "http_expected_calls.json"), "w") as f:
                json.dump([{"method": "GET", "host": "api.example.com", "path": "/users", "body": ""}], f, indent=2)
        if not os.path.exists(readme_path):
            with open(readme_path, "w") as f:
                f.write(f"# Fixture: Vector {vec_id} (http)\n\n")
                f.write(f"Criteria: {criteria}\n\n")
                f.write("## Routes\n")
                f.write("Edit `http_routes.json` to define what the fake server returns.\n\n")
                f.write("## Expected Calls\n")
                f.write("Edit `http_expected_calls.json` to define which HTTP calls your real code should make.\n\n")
                f.write("## Real Command\n")
                f.write("Your `real_cmd` receives `BASE_URL=http://127.0.0.1:<port>` for fixture-aware code.\n")
                f.write("It also receives `HTTP_PROXY` and `HTTPS_PROXY` pointing at the fixture server.\n")
                f.write("Plain `http://` calls to external hostnames can be intercepted without code changes.\n")
                f.write("HTTPS calls are not intercepted in this version; CONNECT hides the encrypted request path.\n")

    elif effect == "db":
        if not os.path.exists(os.path.join(fixture_dir, "schema.sql")):
            with open(os.path.join(fixture_dir, "schema.sql"), "w") as f:
                f.write("-- Schema for test database\n")
                f.write("-- Example:\n")
                f.write("CREATE TABLE IF NOT EXISTS example (\n")
                f.write("    id INTEGER PRIMARY KEY,\n")
                f.write("    value TEXT NOT NULL\n")
                f.write(");\n")
        if not os.path.exists(os.path.join(fixture_dir, "seed.sql")):
            with open(os.path.join(fixture_dir, "seed.sql"), "w") as f:
                f.write("-- Seed data for test database\n")
                f.write("-- Example:\n")
                f.write("-- INSERT INTO example (id, value) VALUES (1, 'test');\n")
        if not os.path.exists(os.path.join(fixture_dir, "db_expected.json")):
            with open(os.path.join(fixture_dir, "db_expected.json"), "w") as f:
                json.dump({"example": [{"id": 1, "value": "expected_value"}]}, f, indent=2)
        if not os.path.exists(readme_path):
            with open(readme_path, "w") as f:
                f.write(f"# Fixture: Vector {vec_id} (db)\n\n")
                f.write(f"Criteria: {criteria}\n\n")
                f.write("## Schema\n")
                f.write("Edit `schema.sql` to define tables. A fresh SQLite DB will be created per test run.\n\n")
                f.write("## Seed Data\n")
                f.write("Edit `seed.sql` to insert initial rows before the real command runs.\n\n")
                f.write("## Expected State\n")
                f.write("Edit `db_expected.json` to define the expected DB state after execution.\n\n")
                f.write("## Real Command\n")
                f.write("Your `real_cmd` will receive `DATABASE_URL=sqlite:///path/to/test.db` as env var.\n")
                f.write("Your code must use `DATABASE_URL` instead of a hardcoded connection string.\n")
    else:
        if not os.path.exists(readme_path):
            with open(readme_path, "w") as f:
                f.write(f"# Fixture: Vector {vec_id} (UNSUPPORTED)\n\n")
                f.write(f"Side effect type '{effect}' is not supported by Golden Demo.\n")
                f.write("Supported types: filesystem, http, db\n")
                f.write("This vector will be reported as [UNSUPPORTED] in drift reports.\n")

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

pending_count   = 0
fixture_count   = 0
vector_count    = 0

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
        write_golden_template(vec_id, criteria, expected_val)
        if has_side_effects:
            write_fixture_scaffold(vec_id, criteria, side_effects)
            fixture_count += 1

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
if fixture_count > 0:
    print(f"Golden Demo: {fixture_count} fixture scaffold(s) created in {fixtures_dir}")
    print("Note: Fill in fixture files before running check-drift on side-effecting vectors.")
EOF
```
