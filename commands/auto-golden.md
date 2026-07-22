---
description: "Generates empty golden templates with an LLM, validates them against example input/output, and asks for approval only when validation fails."
---

# Golden Demo — Auto-Golden Generator

This command uses an LLM (OpenAI or Gemini) to generate implementations for
empty golden examples based on their acceptance criteria, then validates the
generated `execute()` function against the vector's example input/output.

## Steps

1. Check for API keys and interactivity.
2. Read empty templates and their vector metadata.
3. Call LLM API.
4. Validate `execute(example_input) == expected_output`.
5. Write validated golden files; ask for approval only when validation fails.

```bash
python3 - << 'EOF'
import os
import sys
import json
import ast
import re
import getpass
import urllib.request
import urllib.error
import textwrap

spec_dir = ".specify/golden-demo"
golden_dir = os.path.join(spec_dir, "golden")
test_vectors_path = os.path.join(spec_dir, "test-vectors.md")

# Check arguments
auto_approve = "--auto-approve" in sys.argv

# Interactive input helpers
def has_prompt_target():
    return sys.stdin.isatty() or os.path.exists("/dev/tty")

def read_prompt_line(prompt):
    try:
        if os.path.exists("/dev/tty") and not sys.stdin.isatty():
            with open("/dev/tty", "r", encoding="utf-8") as tty:
                print(prompt, end="", flush=True)
                return tty.readline().strip()
    except OSError:
        pass
    if not sys.stdin.isatty():
        return None
    try:
        return input(prompt).strip()
    except EOFError:
        return None

def read_secret(prompt):
    if not has_prompt_target():
        return None
    try:
        return getpass.getpass(prompt).strip()
    except Exception as exc:
        print(f"Golden Demo: Hidden input unavailable ({exc}); falling back to visible input.")
        value = read_prompt_line(prompt)
        return value.strip() if value else None

def prompt_for_llm_api_key():
    if not has_prompt_target():
        return None, None

    print("Golden Demo: No GEMINI_API_KEY or OPENAI_API_KEY found.")
    print("Enter an API key for this run only, or press Enter to skip auto-golden.")
    provider = read_prompt_line("Choose provider [gemini/openai/skip]: ")
    if not provider:
        return None, None

    provider = provider.strip().lower()
    if provider in {"skip", "s", "none", "no", "n"}:
        return None, None
    if provider in {"gemini", "g"}:
        env_name = "GEMINI_API_KEY"
    elif provider in {"openai", "o"}:
        env_name = "OPENAI_API_KEY"
    else:
        print("Golden Demo: Unknown provider; skipping auto-golden.")
        return None, None

    api_key = read_secret(f"Enter your {env_name} for this run: ")
    if not api_key:
        print("Golden Demo: Empty API key; skipping auto-golden.")
        return None, None

    os.environ[env_name] = api_key
    return env_name, api_key

# Check API Keys
openai_key = os.environ.get("OPENAI_API_KEY")
gemini_key = os.environ.get("GEMINI_API_KEY")

if not openai_key and not gemini_key:
    env_name, api_key = prompt_for_llm_api_key()
    if env_name == "GEMINI_API_KEY":
        gemini_key = api_key
    elif env_name == "OPENAI_API_KEY":
        openai_key = api_key
    else:
        print("Golden Demo: Neither OPENAI_API_KEY nor GEMINI_API_KEY found.")
        print("Set a key in your environment, or enter one when prompted, to use this command.")
        sys.exit(0)

# Provider Priority: GEMINI_API_KEY > OPENAI_API_KEY
# If both are set, Gemini is used (Golden Demo ecosystem is Gemini-first).
# If only one is set, that provider is used automatically.
if gemini_key:
    active_provider = "Gemini"
    active_key = gemini_key
elif openai_key:
    active_provider = "OpenAI"
    active_key = openai_key

print(f"Using {active_provider} for auto-golden generation.")

def call_openai(prompt, api_key):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR: {str(e)}"

def call_gemini(prompt, api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0}
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return f"ERROR: {str(e)}"

def extract_code(text):
    if "```python" in text:
        return text.split("```python")[1].split("```")[0].strip()
    return text.replace("```", "").strip()

def parse_test_vectors(path):
    vectors = {}
    if not os.path.exists(path):
        return vectors

    current = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if line.startswith("### Vector "):
                if current.get("id"):
                    vectors[current["id"]] = current
                current = {"id": line.replace("### Vector ", "").strip()}
            elif line.startswith("- Criteria: "):
                current["criteria"] = line[12:].strip()
            elif line.startswith("- Input Type: "):
                current["input_type"] = line[14:].strip()
            elif line.startswith("- Input: "):
                current["example_input"] = line[9:].strip()
            elif line.startswith("- Expected Output: "):
                current["expected_output"] = line[19:].strip()
        if current.get("id"):
            vectors[current["id"]] = current

    for vector in vectors.values():
        vector.setdefault("criteria", "not specified")
        vector.setdefault("example_input", "not specified")
        vector.setdefault("expected_output", "not specified")
        vector.setdefault("input_type", infer_input_type(vector["example_input"]))
    return vectors

def is_empty_template(content):
    if "TODO" in content:
        return True
    return bool(re.search(r"\bpass\b", content))

def vector_id_from_filename(filename):
    match = re.match(r"^vector_(.+)_golden\.py$", filename)
    return match.group(1) if match else None

def parse_literal(value):
    if value is None:
        return None, False
    text = str(value).strip()
    if not text or text == "not specified" or text.lower().startswith("dynamic"):
        return None, False
    try:
        return ast.literal_eval(text), True
    except Exception:
        pass
    try:
        return json.loads(text), True
    except Exception:
        pass
    lowered = text.lower()
    if lowered == "true":
        return True, True
    if lowered == "false":
        return False, True
    if lowered in {"null", "none"}:
        return None, True
    return text, True

def infer_input_type(value):
    parsed, ok = parse_literal(value)
    if not ok:
        return "unknown"
    if isinstance(parsed, list):
        if all(isinstance(item, int) and not isinstance(item, bool) for item in parsed):
            return "list[int]"
        return "list"
    if isinstance(parsed, str):
        return "str"
    if isinstance(parsed, bool):
        return "bool"
    if isinstance(parsed, int):
        return "int"
    if isinstance(parsed, float):
        return "float"
    if isinstance(parsed, dict):
        return "dict"
    return "unknown"

def outputs_match(actual, expected):
    if actual == expected:
        return True
    try:
        return abs(float(actual) - float(expected)) < 1e-9
    except (TypeError, ValueError):
        pass
    return str(actual) == str(expected)

def normalize_generated_code(generated, vec_id, vector):
    raw = textwrap.dedent(extract_code(generated)).strip()
    if not raw:
        return ""

    header = (
        f"# Golden Example for Vector {vec_id}\n"
        f"# Criteria: {vector.get('criteria', 'not specified')}\n"
        f"# Generated by /speckit.auto-golden after example-output validation\n\n"
    )

    if re.search(r"^\s*def\s+execute\s*\(", raw, re.MULTILINE):
        return header + raw.rstrip() + "\n"

    return header + "def execute(input_data):\n" + textwrap.indent(raw, "    ") + "\n"

def validate_generated_code(code, example_input, expected_output):
    input_value, input_ok = parse_literal(example_input)
    expected_value, expected_ok = parse_literal(expected_output)
    if not input_ok or not expected_ok:
        return False, "example input or expected output is not a concrete literal"

    safe_builtins = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "range": range,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }
    namespace = {"__builtins__": safe_builtins}
    try:
        exec(code, namespace)
    except Exception as exc:
        return False, f"generated code could not be executed: {exc}"

    execute_fn = namespace.get("execute")
    if not callable(execute_fn):
        return False, "generated code did not define execute(input_data)"

    try:
        actual = execute_fn(input_value)
    except Exception as exc:
        return False, f"execute({example_input}) raised: {exc}"

    if outputs_match(actual, expected_value):
        return True, f"execute({example_input}) returned {actual!r}"
    return False, f"execute({example_input}) returned {actual!r}, expected {expected_value!r}"

def ask_yes_no(prompt):
    if not has_prompt_target():
        return False
    try:
        ans = read_prompt_line(prompt)
        return (ans or "").strip().lower() == "y"
    except Exception as exc:
        print(f"Warning: Could not read interactive input ({exc}).")
        return False

if not os.path.exists(golden_dir):
    print("Golden Demo: No golden directory found. Run /speckit.plan first.")
    sys.exit(0)

vectors_by_id = parse_test_vectors(test_vectors_path)
if not vectors_by_id:
    print("Golden Demo: No test vector metadata found. Run /speckit.plan first.")
    sys.exit(0)

# Find empty templates
templates = []
for filename in os.listdir(golden_dir):
    if filename.endswith("_golden.py"):
        filepath = os.path.join(golden_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            if is_empty_template(content):
                templates.append((filename, filepath, content))

if not templates:
    print("Golden Demo: No empty golden templates found. All set!")
    sys.exit(0)

suggestions_md = "# Golden Demo — LLM Suggestions\n\n"

# Interactive prompt helper
def is_interactive():
    return has_prompt_target()

can_prompt = is_interactive() and not auto_approve
written_count = 0
skipped_count = 0

for filename, filepath, content in templates:
    print(f"Generating implementation for {filename}...")

    vec_id = vector_id_from_filename(filename)
    vector = vectors_by_id.get(vec_id or "")
    if not vector:
        skipped_count += 1
        reason = f"No matching vector metadata found for {filename}"
        print(f"SKIPPED {filename}: {reason}")
        suggestions_md += f"## {filename}\nSKIPPED: {reason}\n\n"
        continue

    criteria = vector.get("criteria", "not specified")
    input_type = vector.get("input_type", "unknown")
    example_input = vector.get("example_input", "not specified")
    expected_output = vector.get("expected_output", "not specified")
    
    prompt = (
        "Write a Python function named execute(input_data) that\n"
        f" satisfies this criterion: {criteria}.\n"
        f" Input type: {input_type}.\n"
        f" For example: execute({example_input}) should return\n"
        f" {expected_output}. Return only the function body, no\n"
        " explanations, no markdown."
    )
    
    if active_provider == "OpenAI":
        generated = call_openai(prompt, active_key)
    else:
        generated = call_gemini(prompt, active_key)
    
    if "ERROR:" in generated:
        skipped_count += 1
        print(f"SKIPPED {filename}: LLM generation failed: {generated}")
        suggestions_md += f"## {filename}\nSKIPPED: LLM generation failed\n\n```text\n{generated}\n```\n\n"
        continue

    code = normalize_generated_code(generated, vec_id, vector)
    if not code:
        skipped_count += 1
        reason = "LLM returned empty code"
        print(f"SKIPPED {filename}: {reason}")
        suggestions_md += f"## {filename}\nSKIPPED: {reason}\n\n"
        continue

    validation_ok, validation_message = validate_generated_code(code, example_input, expected_output)
    
    write_to_disk = validation_ok
    
    if validation_ok:
        print(f"Validated {filename}: {validation_message}")
    else:
        print("\n" + "="*40)
        print(f"Generated implementation for {filename} did not validate:")
        print(validation_message)
        print("-" * 40)
        print(code)
        print("="*40 + "\n")
        if can_prompt and ask_yes_no("Accept this implementation anyway? [y/N]: "):
            write_to_disk = True
            
    if write_to_disk:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)
        written_count += 1
        print(f"Written to {filepath}\n")
    else:
        skipped_count += 1
        print(f"SKIPPED {filename} (suggestion saved to suggestions.md)\n")
        suggestions_md += (
            f"## {filename}\n"
            f"SKIPPED: {validation_message}\n\n"
            f"- Criteria: {criteria}\n"
            f"- Input Type: {input_type}\n"
            f"- Example Input: {example_input}\n"
            f"- Expected Output: {expected_output}\n\n"
            "```python\n"
            f"{code}"
            "```\n\n"
        )

if skipped_count > 0:
    with open(os.path.join(spec_dir, "suggestions.md"), "w", encoding="utf-8") as f:
        f.write(suggestions_md)
    print(f"Golden Demo: {skipped_count} implementation(s) SKIPPED.")
    print(f"Suggestions saved to {os.path.join(spec_dir, 'suggestions.md')}")

print(f"Golden Demo: {written_count} golden implementation(s) written, {skipped_count} skipped.")

sys.exit(0)
EOF
```
