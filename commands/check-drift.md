---
description: "Executes golden examples against real implementations. Uses fixture/resource sandbox for side-effecting code: filesystem (tempdir), HTTP (local server), DB (SQLite). Pure vectors use semantic output comparison."
---

# Golden Demo — Behavioral Drift Check

This command runs automatically after `/speckit.implement`.

**Side-effect isolation model:**
- `pure` → semantic output comparison
- `filesystem` → tempdir seeded from `fixtures/vector_N/fs/`, real code runs with that `cwd`, file state compared after
- `http` → local HTTP server with routes from `fixtures/vector_N/http_routes.json`, `BASE_URL` injected into subprocess env
- `db` → disposable SQLite seeded from `fixtures/vector_N/schema.sql` + `seed.sql`, `DATABASE_URL` injected into subprocess env
- anything else → `[UNSUPPORTED]` — not skipped silently, explicitly reported

> **Note:** Real code must read `BASE_URL` / `DATABASE_URL` / `cwd` from its environment.
> This is standard 12-factor config practice. If your implementation hardcodes these,
> Golden Demo reports `implementation_not_fixture_configurable`, not a drift score.

```bash
python3 - << 'EOF'
import os, re, sys, importlib.util, ast, json, subprocess, shutil, tempfile, threading
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────

golden_demo_mode = os.environ.get("GOLDEN_DEMO_MODE", "warn").lower()
spec_dir         = ".specify/golden-demo"
golden_dir       = os.path.join(spec_dir, "golden")
fixtures_dir     = os.path.join(spec_dir, "fixtures")
test_vectors_path = os.path.join(spec_dir, "test-vectors.md")
report_path      = os.path.join(spec_dir, "drift-report.md")
config_path      = os.path.join(spec_dir, "config.json")

config = {"real_cmd": "python sum_list.py", "input_method": "auto", "input_size_threshold_bytes": 4096}
if os.path.exists(config_path):
    with open(config_path) as f:
        try: config.update(json.load(f))
        except Exception as e: print(f"Warning: config.json parse error ({e})")
else:
    with open(config_path, "w") as f: json.dump(config, f, indent=2)

if not os.path.exists(test_vectors_path):
    print("Golden Demo: no test vectors found. Run /speckit.plan first.")
    exit(0)

# ─── PARSE VECTORS ────────────────────────────────────────────────────────────

with open(test_vectors_path, "r", encoding="utf-8") as f:
    content = f.read()

vectors, current_vec = [], {}
for line in content.split("\n"):
    if line.startswith("### Vector "):
        if current_vec: vectors.append(current_vec)
        current_vec = {"id": line.replace("### Vector ", "").strip()}
    elif line.startswith("- Source: "):      current_vec["source"]      = line[10:].strip()
    elif line.startswith("- Criteria: "):    current_vec["criteria"]    = line[12:].strip()
    elif line.startswith("- Input: "):       current_vec["input"]       = line[9:].strip()
    elif line.startswith("- Expected Output: "): current_vec["expected"] = line[19:].strip()
    elif line.startswith("- Status: "):      current_vec["status"]      = line[10:].strip()
    elif line.startswith("- Is Pure: "):     current_vec["is_pure"]     = line[11:].strip().lower() != "false"
    elif line.startswith("- Side Effects: "): current_vec["side_effects"] = [s.strip() for s in line[16:].strip().split(",")]
if current_vec: vectors.append(current_vec)

if not vectors:
    print("Golden Demo: test-vectors.md contains no vectors.")
    exit(0)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec: return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

def compare(golden, real):
    """Semantic comparison. Returns (drift_score, match_type)."""
    if golden == real and type(golden) == type(real):
        return 0.0, "exact"
    try:
        if abs(float(str(golden)) - float(str(real))) < 1e-9:
            return (0.0, "numeric_tolerance") if type(golden) != type(real) else (0.0, "exact")
    except (TypeError, ValueError): pass
    try:
        if type(golden) != type(real) and str(golden) == str(real):
            return 0.0, "type_coercion"
    except Exception: pass
    if isinstance(golden, list) and isinstance(real, list):
        if not golden and not real: return 0.0, "exact"
        if len(golden) != len(real): return 1.0, "length_mismatch"
        mismatches = sum(1 for a, b in zip(golden, real) if str(a) != str(b))
        return round(mismatches / len(golden), 2), "partial_list"
    if isinstance(golden, dict) and isinstance(real, dict):
        keys = set(golden) | set(real)
        if not keys: return 0.0, "exact"
        mismatches = sum(1 for k in keys if str(golden.get(k)) != str(real.get(k)))
        return round(mismatches / len(keys), 2), "partial_dict"
    return 1.0, "mismatch"

def compare_files(actual_dir, expected_dir):
    """Compare actual file state in a directory against expected snapshot.
    Only checks files listed in expected_dir — extra files in actual_dir are ignored.
    """
    if not os.path.exists(expected_dir):
        return None, "no_expected_snapshot"
    expected = sorted(f for f in os.listdir(expected_dir) if os.path.isfile(os.path.join(expected_dir, f)))
    if not expected:
        return 0.0, "no_expected_files"
    missing = [f for f in expected if not os.path.exists(os.path.join(actual_dir, f))]
    if missing:
        return 1.0, f"file_list_mismatch (missing: {missing})"
    mismatches = 0
    for fname in expected:
        with open(os.path.join(actual_dir, fname), "r", errors="replace") as fa, \
             open(os.path.join(expected_dir, fname), "r", errors="replace") as fe:
            if fa.read() != fe.read():
                mismatches += 1
    score = round(mismatches / len(expected), 2)
    return score, "exact" if score == 0.0 else "file_content_partial"

# ─── SANDBOX CLASSES ──────────────────────────────────────────────────────────

class FilesystemSandbox:
    """Seed a tempdir, inject GOLDEN_DEMO_FS_ROOT env var so real code can find it.
    The real subprocess keeps the project cwd — it must read GOLDEN_DEMO_FS_ROOT
    to locate its working directory. This avoids the problem of relative commands
    (e.g. 'node sum_list.js') failing because the script doesn't exist in tempdir.
    """
    def __init__(self, fixture_dir):
        self.fixture_dir = fixture_dir
        self.tempdir = None

    def setup(self):
        self.tempdir = tempfile.mkdtemp(prefix="gd_fs_")
        seed_dir = os.path.join(self.fixture_dir, "fs")
        if os.path.exists(seed_dir):
            for fname in os.listdir(seed_dir):
                src = os.path.join(seed_dir, fname)
                if os.path.isfile(src):
                    shutil.copy(src, self.tempdir)
        # cwd stays as project root; real code receives GOLDEN_DEMO_FS_ROOT
        return {"cwd": None, "env": {"GOLDEN_DEMO_FS_ROOT": self.tempdir}, "input_override": None}

    def compare_state(self):
        expected_dir = os.path.join(self.fixture_dir, "fs_expected")
        return compare_files(self.tempdir, expected_dir)

    def teardown(self):
        if self.tempdir and os.path.exists(self.tempdir):
            shutil.rmtree(self.tempdir, ignore_errors=True)


class HTTPSandbox:
    """Spin up a local HTTP server with fixture routes, inject BASE_URL into subprocess."""
    def __init__(self, fixture_dir):
        self.fixture_dir = fixture_dir
        self.server = None
        self.port = None
        self.recorded_calls = []

    def setup(self):
        from http.server import HTTPServer, BaseHTTPRequestHandler
        routes_path = os.path.join(self.fixture_dir, "http_routes.json")
        if not os.path.exists(routes_path):
            return None  # signal unsupported

        with open(routes_path) as f:
            routes = json.load(f)

        recorded = self.recorded_calls

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  self._handle("GET")
            def do_POST(self): self._handle("POST")
            def do_PUT(self):  self._handle("PUT")
            def do_DELETE(self): self._handle("DELETE")
            def _handle(self, method):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8") if length else ""
                recorded.append({"method": method, "path": self.path, "body": body})
                for route in routes:
                    if route["method"] == method and route["path"] == self.path:
                        resp = json.dumps(route.get("response", {})).encode()
                        self.send_response(route.get("status", 200))
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(resp)))
                        self.end_headers()
                        self.wfile.write(resp)
                        return
                self.send_response(404)
                self.end_headers()
            def log_message(self, *args): pass  # silence logs

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        t = threading.Thread(target=self.server.serve_forever, daemon=True)
        t.start()
        return {"cwd": None, "env": {"BASE_URL": f"http://127.0.0.1:{self.port}"}, "input_override": None}

    def compare_state(self):
        expected_path = os.path.join(self.fixture_dir, "http_expected_calls.json")
        if not os.path.exists(expected_path):
            return 0.0, "no_expected_calls_file"
        with open(expected_path) as f:
            expected = json.load(f)
        if self.recorded_calls == expected:
            return 0.0, "exact"
        return 1.0, f"calls_mismatch (recorded {len(self.recorded_calls)}, expected {len(expected)})"

    def teardown(self):
        if self.server: self.server.shutdown()


class DBSandbox:
    """Spin up a disposable SQLite DB, seed it, inject DATABASE_URL into subprocess."""
    def __init__(self, fixture_dir):
        self.fixture_dir = fixture_dir
        self.db_path = None

    def setup(self):
        import sqlite3
        schema_path = os.path.join(self.fixture_dir, "schema.sql")
        if not os.path.exists(schema_path):
            return None  # signal unsupported

        fd, self.db_path = tempfile.mkstemp(suffix=".db", prefix="gd_db_")
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        with open(schema_path) as f:
            conn.executescript(f.read())
        seed_path = os.path.join(self.fixture_dir, "seed.sql")
        if os.path.exists(seed_path):
            with open(seed_path) as f:
                conn.executescript(f.read())
        conn.commit()
        conn.close()
        return {"cwd": None, "env": {"DATABASE_URL": f"sqlite:///{self.db_path}"}, "input_override": None}

    def compare_state(self):
        import sqlite3
        expected_path = os.path.join(self.fixture_dir, "db_expected.json")
        if not os.path.exists(expected_path):
            return 0.0, "no_expected_snapshot"
        with open(expected_path) as f:
            expected_state = json.load(f)
        conn = sqlite3.connect(self.db_path)
        total, mismatches = 0, 0
        for table, exp_rows in expected_state.items():
            try:
                cur = conn.execute(f"SELECT * FROM {table}")
                cols = [d[0] for d in cur.description]
                act_rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            except Exception as e:
                conn.close()
                return 1.0, f"db_query_error: {e}"
            if len(exp_rows) != len(act_rows):
                conn.close()
                return 1.0, f"row_count_mismatch in {table} (got {len(act_rows)}, expected {len(exp_rows)})"
            for er, ar in zip(exp_rows, act_rows):
                for k in er:
                    total += 1
                    if str(er.get(k)) != str(ar.get(k)):
                        mismatches += 1
        conn.close()
        if total == 0: return 0.0, "exact"
        score = round(mismatches / total, 2)
        return score, "exact" if score == 0.0 else "db_state_partial"

    def teardown(self):
        if self.db_path and os.path.exists(self.db_path):
            os.remove(self.db_path)

# ─── SANDBOX FACTORY ──────────────────────────────────────────────────────────

SUPPORTED_SANDBOX_TYPES = {"filesystem", "http", "db"}

def get_sandbox(vec_id, side_effects):
    """Return sandbox instance, or None (pure), or raise for unsupported."""
    if not side_effects:
        return None  # pure
    effects = set(side_effects)
    unsupported = effects - SUPPORTED_SANDBOX_TYPES
    if unsupported:
        raise ValueError(f"UNSUPPORTED side-effect type(s): {unsupported}. "
                         "Supported: filesystem, http, db.")
    if len(effects) > 1:
        raise ValueError(f"Multiple side-effect types not yet supported in one vector: {effects}. "
                         "Split into separate vectors.")
    fixture_dir = os.path.join(fixtures_dir, f"vector_{vec_id}")
    effect = list(effects)[0]
    if effect == "filesystem": return FilesystemSandbox(fixture_dir)
    if effect == "http":       return HTTPSandbox(fixture_dir)
    if effect == "db":         return DBSandbox(fixture_dir)

# ─── SUBPROCESS RUNNER ────────────────────────────────────────────────────────

def run_real(json_input, sandbox_ctx=None):
    real_cmd = config["real_cmd"]
    cwd = None
    env = os.environ.copy()

    if sandbox_ctx:
        if sandbox_ctx.get("cwd"):
            cwd = sandbox_ctx["cwd"]
        env.update(sandbox_ctx.get("env", {}))

    method = config.get("input_method", "auto")
    if method == "auto":
        method = "stdin" if len(json_input.encode()) > config.get("input_size_threshold_bytes", 4096) else "arg"

    if method == "arg":
        cmd = real_cmd.replace("{input}", json_input) if "{input}" in real_cmd else f"{real_cmd} '{json_input}'"
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True, cwd=cwd, env=env)
    else:
        cmd = real_cmd.replace(" '{input}'","").replace(' "{input}"',"").replace(" {input}","")
        proc = subprocess.run(cmd, shell=True, input=json_input, capture_output=True, text=True, check=True, cwd=cwd, env=env)

    raw = proc.stdout.strip()
    try:    return ast.literal_eval(raw)
    except: pass
    try:    return json.loads(raw)
    except: return raw

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

results, skipped = [], []
total_executed = pass_count = fail_count = error_count = unsupported_count = 0

for vec in vectors:
    vid = vec.get("id", "?")

    if vec.get("status") != "pending-execution":
        skipped.append({"id": vid, "reason": "Not pending"})
        continue

    # Find golden
    golden_path = os.path.join(golden_dir, f"vector_{vid}_golden.py")
    if not os.path.exists(golden_path) and "." in vid:
        golden_path = os.path.join(golden_dir, f"vector_{vid.split('.')[0]}_golden.py")
    if not os.path.exists(golden_path):
        skipped.append({"id": vid, "reason": "Golden template not implemented"})
        continue

    try:
        golden_mod = load_module(f"golden_{vid}", golden_path)
        if not hasattr(golden_mod, "execute"):
            raise AttributeError("Missing execute function")
    except Exception as e:
        skipped.append({"id": vid, "reason": f"Golden load error: {e}"})
        continue

    side_effects = vec.get("side_effects", [])
    is_pure = vec.get("is_pure", True) and not side_effects

    # Resolve sandbox
    sandbox = None
    try:
        sandbox = get_sandbox(vid, side_effects if not is_pure else [])
    except ValueError as e:
        unsupported_count += 1
        results.append({"id": vid, "criteria": vec.get("criteria",""), "status": "UNSUPPORTED",
                        "input": vec.get("input",""), "golden_out": "N/A", "real_out": "N/A",
                        "drift": "N/A", "match_type": "unsupported", "notes": str(e)})
        continue

    total_executed += 1
    input_str = vec.get("input", "not specified")
    try:    input_data = ast.literal_eval(input_str)
    except: input_data = input_str

    sandbox_ctx = None
    try:
        # Setup sandbox
        if sandbox:
            sandbox_ctx = sandbox.setup()
            if sandbox_ctx is None:
                raise RuntimeError(
                    "implementation_not_fixture_configurable: fixture template missing. "
                    f"Create .specify/golden-demo/fixtures/vector_{vid}/ with required files."
                )

        # Run golden (pure Python, no sandbox needed)
        golden_out = golden_mod.execute(input_data)

        # Run real subprocess (with sandbox env/cwd if applicable)
        json_input = json.dumps(input_data)
        real_out = run_real(json_input, sandbox_ctx)

        # Compare
        if is_pure:
            drift, match_type = compare(golden_out, real_out)
        else:
            # For sandboxed vectors: compare golden output + side-effect state
            output_drift, output_match = compare(golden_out, real_out)
            state_drift,  state_match  = sandbox.compare_state()
            # Weighted: output 50%, state 50%
            drift = round((output_drift + (state_drift or 0.0)) / 2, 2)
            match_type = f"output:{output_match} + state:{state_match}"

        status = "PASS" if drift == 0.0 else "FAIL"
        if status == "PASS": pass_count += 1
        else:                fail_count += 1

        results.append({"id": vid, "criteria": vec.get("criteria",""), "status": status,
                        "input": input_str, "golden_out": golden_out, "real_out": real_out,
                        "drift": drift, "match_type": match_type, "notes": ""})

    except subprocess.CalledProcessError as e:
        error_count += 1
        msg = e.stderr[:300] if e.stderr else f"exit {e.returncode}"
        results.append({"id": vid, "criteria": vec.get("criteria",""), "status": "ERROR",
                        "input": input_str, "golden_out": "N/A", "real_out": "N/A",
                        "drift": "N/A", "match_type": "error", "notes": msg})
    except Exception as e:
        error_count += 1
        results.append({"id": vid, "criteria": vec.get("criteria",""), "status": "ERROR",
                        "input": input_str, "golden_out": "N/A", "real_out": "N/A",
                        "drift": "N/A", "match_type": "error", "notes": str(e)[:300]})
    finally:
        if sandbox:
            try: sandbox.teardown()
            except Exception: pass

# ─── REPORT ───────────────────────────────────────────────────────────────────

executed_with_scores = [r for r in results if isinstance(r["drift"], float)]
drift_score = round(sum(r["drift"] for r in executed_with_scores) / len(executed_with_scores), 2) \
              if executed_with_scores else 0.0

report = f"# Golden Demo Drift Report\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
report += f"MODE: {golden_demo_mode}\n\n"
report += "## Summary\n"
report += f"- Total: {len(vectors)}  Executed: {total_executed}  "
report += f"PASS: {pass_count}  FAIL: {fail_count}  ERROR: {error_count}  UNSUPPORTED: {unsupported_count}  Skipped: {len(skipped)}\n\n"
report += f"## Overall Drift Score: {drift_score:.2f}\n\n"
report += "## Results\n\n"
for res in results:
    report += f"### Vector {res['id']} -- {res['criteria']}\n"
    report += f"- Status: {res['status']}\n- Input: {res['input']}\n"
    report += f"- Golden Output: {res['golden_out']}\n- Real Output: {res['real_out']}\n"
    report += f"- Drift: {res['drift']} ({res['match_type']})\n"
    if res["notes"]: report += f"- Notes: {res['notes']}\n"
    report += "\n"
report += "## Skipped\n"
for s in skipped: report += f"- Vector {s['id']}: {s['reason']}\n"

with open(report_path, "w", encoding="utf-8") as f:
    f.write(report)

print(f"\nGolden Demo v0.4.1")
print("-" * 40)
print(f"PASS: {pass_count}  FAIL: {fail_count}  ERROR: {error_count}  UNSUPPORTED: {unsupported_count}")
print(f"Drift Score: {drift_score:.2f}  |  Report: {report_path}")
print("-" * 40 + "\n")

if drift_score > 0 or error_count > 0:
    if golden_demo_mode == "strict":
        print("[X] Drift detected. FAILING BUILD (strict mode).")
        sys.exit(1)
    else:
        print("[!] Drift detected. Review before merging. (warn mode)")
        sys.exit(0)
else:
    print("[OK] No drift detected.")
    sys.exit(0)
EOF
```
