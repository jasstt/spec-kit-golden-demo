---
description: "Automatically generates implementations for empty golden templates using an LLM. Requires human approval unless --auto-approve is passed."
---

# Golden Demo — Auto-Golden Generator

This command uses an LLM (OpenAI or Gemini) to generate implementations for
empty golden examples based on their acceptance criteria.

## Steps

1. Check for API keys and interactivity.
2. Read empty templates.
3. Call LLM API and prompt for approval.

```bash
python3 - << 'EOF'
import os
import sys
import json
import urllib.request
import urllib.error
import textwrap

spec_dir = ".specify/golden-demo"
golden_dir = os.path.join(spec_dir, "golden")

# Check arguments
auto_approve = "--auto-approve" in sys.argv

# Check API Keys
openai_key = os.environ.get("OPENAI_API_KEY")
gemini_key = os.environ.get("GEMINI_API_KEY")

if not openai_key and not gemini_key:
    print("Golden Demo: Neither OPENAI_API_KEY nor GEMINI_API_KEY found.")
    print("Set GEMINI_API_KEY or OPENAI_API_KEY to use this command.")
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

if not os.path.exists(golden_dir):
    print("Golden Demo: No golden directory found. Run /speckit.plan first.")
    sys.exit(0)

# Find empty templates
templates = []
for filename in os.listdir(golden_dir):
    if filename.endswith("_golden.py"):
        filepath = os.path.join(golden_dir, filename)
        with open(filepath, "r") as f:
            content = f.read()
            if "TODO: Implement this pure function" in content:
                templates.append((filename, filepath, content))

if not templates:
    print("Golden Demo: No empty golden templates found. All set!")
    sys.exit(0)

suggestions_md = "# Golden Demo — LLM Suggestions\n\n"

# Interactive prompt helper
def is_interactive():
    return sys.stdin.isatty()

can_prompt = is_interactive() and not auto_approve

for filename, filepath, content in templates:
    print(f"Generating implementation for {filename}...")
    
    prompt = f"""
    You are writing a Python pure function named `execute(input_data)` for a testing oracle.
    Here is the template:
    ```python
    {content}
    ```
    Please provide ONLY the raw python code for the complete file. Do not use external libraries. 
    Ensure the function handles edge cases cleanly and deterministically.
    """
    
    if active_provider == "OpenAI":
        generated = call_openai(prompt, active_key)
    else:
        generated = call_gemini(prompt, active_key)
        
    code = extract_code(generated)
    
    if "ERROR:" in code:
        print(f"Failed to generate for {filename}: {code}")
        continue
        
    print("\n" + "="*40)
    print(f"Proposed implementation for {filename}:")
    print("-" * 40)
    print(code)
    print("="*40 + "\n")
    
    write_to_disk = auto_approve
    
    if can_prompt:
        # Prompt user directly via terminal
        try:
            # Reopen tty if needed for bash hooks where stdin might be piped
            try:
                tty = open('/dev/tty', 'r')
                print("Accept this implementation? [y/N]: ", end="", flush=True)
                ans = tty.readline().strip().lower()
                tty.close()
            except OSError:
                ans = input("Accept this implementation? [y/N]: ").strip().lower()
                
            if ans == 'y':
                write_to_disk = True
        except Exception as e:
            print(f"Warning: Could not read interactive input ({e}).")
            
    if write_to_disk:
        with open(filepath, "w") as f:
            f.write(code)
        print(f"✅ Written to {filepath}\n")
    else:
        print(f"⏭️  Skipped {filename} (Suggestion saved to suggestions.md)\n")
        suggestions_md += f"## {filename}\n```python\n{code}\n```\n\n"

if not write_to_disk and not auto_approve:
    with open(os.path.join(spec_dir, "suggestions.md"), "w") as f:
        f.write(suggestions_md)
    print("Golden Demo: Some implementations were not auto-approved.")
    print(f"Suggestions saved to {os.path.join(spec_dir, 'suggestions.md')}")

sys.exit(0)
EOF
```
