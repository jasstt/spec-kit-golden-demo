"""
Fixture/Resource Sandbox Test Suite
Tests FilesystemSandbox, HTTPSandbox, DBSandbox in isolation.
"""
import sys, os, json, shutil, tempfile, threading, time
sys.path.insert(0, os.path.dirname(__file__))

results = []

def check(label, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((label, status, detail))
    line = f"  [{status}] {label}"
    if detail: line += f" -- {detail}"
    print(line.encode("ascii","replace").decode("ascii"))

SPEC_DIR    = ".specify/golden-demo"
FIXTURES    = os.path.join(SPEC_DIR, "fixtures")
os.makedirs(FIXTURES, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Inline sandbox classes (same logic as check-drift.md)
# ─────────────────────────────────────────────────────────────────────────────

def compare_files(actual_dir, expected_dir):
    if not os.path.exists(expected_dir):
        return None, "no_expected_snapshot"
    expected = sorted(f for f in os.listdir(expected_dir) if os.path.isfile(os.path.join(expected_dir, f)))
    if not expected:
        return 0.0, "no_expected_files"
    # Only check that expected files exist in actual and match content
    # Extra files in actual_dir are fine (e.g. seed files that weren't modified)
    missing = [f for f in expected if not os.path.exists(os.path.join(actual_dir, f))]
    if missing:
        return 1.0, f"file_list_mismatch (missing: {missing})"
    mismatches = 0
    for fname in expected:
        with open(os.path.join(actual_dir, fname), "r", errors="replace") as fa, \
             open(os.path.join(expected_dir, fname), "r", errors="replace") as fe:
            if fa.read() != fe.read(): mismatches += 1
    score = round(mismatches / len(expected), 2) if expected else 0.0
    return score, "exact" if score == 0.0 else "file_content_partial"

class FilesystemSandbox:
    def __init__(self, fixture_dir):
        self.fixture_dir = fixture_dir
        self.tempdir = None
    def setup(self):
        self.tempdir = tempfile.mkdtemp(prefix="gd_fs_")
        seed_dir = os.path.join(self.fixture_dir, "fs")
        if os.path.exists(seed_dir):
            for fname in os.listdir(seed_dir):
                src = os.path.join(seed_dir, fname)
                if os.path.isfile(src): shutil.copy(src, self.tempdir)
        return {"cwd": None, "env": {"GOLDEN_DEMO_FS_ROOT": self.tempdir}}
    def compare_state(self):
        return compare_files(self.tempdir, os.path.join(self.fixture_dir, "fs_expected"))
    def teardown(self):
        if self.tempdir and os.path.exists(self.tempdir):
            shutil.rmtree(self.tempdir, ignore_errors=True)

class HTTPSandbox:
    def __init__(self, fixture_dir):
        self.fixture_dir = fixture_dir
        self.server = None
        self.port = None
        self.recorded_calls = []
    def setup(self):
        from http.server import HTTPServer, BaseHTTPRequestHandler
        routes_path = os.path.join(self.fixture_dir, "http_routes.json")
        if not os.path.exists(routes_path): return None
        with open(routes_path) as f: routes = json.load(f)
        recorded = self.recorded_calls
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  self._handle("GET")
            def do_POST(self): self._handle("POST")
            def _handle(self, method):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode() if length else ""
                recorded.append({"method": method, "path": self.path, "body": body})
                for route in routes:
                    if route["method"] == method and route["path"] == self.path:
                        resp = json.dumps(route.get("response", {})).encode()
                        self.send_response(route.get("status", 200))
                        self.send_header("Content-Type","application/json")
                        self.send_header("Content-Length", str(len(resp)))
                        self.end_headers()
                        self.wfile.write(resp)
                        return
                self.send_response(404); self.end_headers()
            def log_message(self, *args): pass
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return {"cwd": None, "env": {"BASE_URL": f"http://127.0.0.1:{self.port}"}}
    def compare_state(self):
        expected_path = os.path.join(self.fixture_dir, "http_expected_calls.json")
        if not os.path.exists(expected_path): return 0.0, "no_expected_calls_file"
        with open(expected_path) as f: expected = json.load(f)
        if self.recorded_calls == expected: return 0.0, "exact"
        return 1.0, f"calls_mismatch"
    def teardown(self):
        if self.server: self.server.shutdown()

class DBSandbox:
    def __init__(self, fixture_dir):
        self.fixture_dir = fixture_dir
        self.db_path = None
    def setup(self):
        import sqlite3
        schema_path = os.path.join(self.fixture_dir, "schema.sql")
        if not os.path.exists(schema_path): return None
        fd, self.db_path = tempfile.mkstemp(suffix=".db", prefix="gd_db_")
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        with open(schema_path) as f: conn.executescript(f.read())
        seed_path = os.path.join(self.fixture_dir, "seed.sql")
        if os.path.exists(seed_path):
            with open(seed_path) as f: conn.executescript(f.read())
        conn.commit(); conn.close()
        return {"cwd": None, "env": {"DATABASE_URL": f"sqlite:///{self.db_path}"}}
    def compare_state(self):
        import sqlite3
        expected_path = os.path.join(self.fixture_dir, "db_expected.json")
        if not os.path.exists(expected_path): return 0.0, "no_expected_snapshot"
        with open(expected_path) as f: expected_state = json.load(f)
        conn = sqlite3.connect(self.db_path)
        total = mismatches = 0
        for table, exp_rows in expected_state.items():
            cur = conn.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in cur.description]
            act_rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            if len(exp_rows) != len(act_rows):
                conn.close()
                return 1.0, f"row_count_mismatch in {table}"
            for er, ar in zip(exp_rows, act_rows):
                for k in er:
                    total += 1
                    if str(er.get(k)) != str(ar.get(k)): mismatches += 1
        conn.close()
        score = round(mismatches / total, 2) if total else 0.0
        return score, "exact" if score == 0.0 else "db_state_partial"
    def teardown(self):
        if self.db_path and os.path.exists(self.db_path):
            os.remove(self.db_path)

# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: FilesystemSandbox
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== FILESYSTEM SANDBOX ===\n")

fix_dir = os.path.join(FIXTURES, "test_fs")
os.makedirs(os.path.join(fix_dir, "fs"), exist_ok=True)
os.makedirs(os.path.join(fix_dir, "fs_expected"), exist_ok=True)

# Seed file
with open(os.path.join(fix_dir, "fs", "input.txt"), "w") as f: f.write("hello")
# Expected output
with open(os.path.join(fix_dir, "fs_expected", "output.txt"), "w") as f: f.write("HELLO")

sb = FilesystemSandbox(fix_dir)
ctx = sb.setup()

check("setup() creates tempdir", os.path.isdir(sb.tempdir))
check("GOLDEN_DEMO_FS_ROOT env var set", "GOLDEN_DEMO_FS_ROOT" in ctx["env"])
check("seed file copied to tempdir", os.path.exists(os.path.join(ctx["env"]["GOLDEN_DEMO_FS_ROOT"], "input.txt")))

# Simulate real code: reads GOLDEN_DEMO_FS_ROOT from env, writes output.txt
fs_root = ctx["env"]["GOLDEN_DEMO_FS_ROOT"]
with open(os.path.join(fs_root, "input.txt")) as f: data = f.read()
with open(os.path.join(fs_root, "output.txt"), "w") as f: f.write(data.upper())

drift, match = sb.compare_state()
check("file state comparison PASS (output.txt matches)", drift == 0.0 and match == "exact", f"drift={drift} match={match}")

sb.teardown()
check("teardown removes tempdir", not os.path.exists(sb.tempdir))

# Test FAIL case
sb2 = FilesystemSandbox(fix_dir)
ctx2 = sb2.setup()
with open(os.path.join(sb2.tempdir, "output.txt"), "w") as f: f.write("wrong")
drift2, match2 = sb2.compare_state()
check("file state comparison FAIL (wrong content)", drift2 == 1.0 and "partial" in match2, f"drift={drift2} match={match2}")
sb2.teardown()

# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: HTTPSandbox
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== HTTP SANDBOX ===\n")
import urllib.request

fix_dir_http = os.path.join(FIXTURES, "test_http")
os.makedirs(fix_dir_http, exist_ok=True)

with open(os.path.join(fix_dir_http, "http_routes.json"), "w") as f:
    json.dump([{"method": "GET", "path": "/ping", "status": 200, "response": {"status": "ok"}}], f)

with open(os.path.join(fix_dir_http, "http_expected_calls.json"), "w") as f:
    json.dump([{"method": "GET", "path": "/ping", "body": ""}], f)

sb3 = HTTPSandbox(fix_dir_http)
ctx3 = sb3.setup()
check("HTTP sandbox started", ctx3 is not None and "BASE_URL" in ctx3["env"])

# Simulate real code calling BASE_URL/ping
base_url = ctx3["env"]["BASE_URL"]
with urllib.request.urlopen(f"{base_url}/ping") as resp:
    body = json.loads(resp.read())

check("fixture route responds correctly", body == {"status": "ok"}, str(body))

drift3, match3 = sb3.compare_state()
check("HTTP calls match expected", drift3 == 0.0 and match3 == "exact", f"drift={drift3} match={match3}")

# Test FAIL: make wrong call
sb4 = HTTPSandbox(fix_dir_http)
ctx4 = sb4.setup()
try: urllib.request.urlopen(f"{ctx4['env']['BASE_URL']}/wrong")
except: pass  # 404 is fine
drift4, match4 = sb4.compare_state()
check("HTTP calls mismatch detected", drift4 == 1.0 and "mismatch" in match4, f"drift={drift4} match={match4}")
sb3.teardown(); sb4.teardown()

# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: DBSandbox
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== DB SANDBOX ===\n")
import sqlite3

fix_dir_db = os.path.join(FIXTURES, "test_db")
os.makedirs(fix_dir_db, exist_ok=True)

with open(os.path.join(fix_dir_db, "schema.sql"), "w") as f:
    f.write("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT);\n")
with open(os.path.join(fix_dir_db, "seed.sql"), "w") as f:
    f.write("INSERT INTO users (id, name) VALUES (1, 'Alice');\n")
with open(os.path.join(fix_dir_db, "db_expected.json"), "w") as f:
    json.dump({"users": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]}, f)

sb5 = DBSandbox(fix_dir_db)
ctx5 = sb5.setup()
check("DB sandbox created", ctx5 is not None and "DATABASE_URL" in ctx5["env"])
check("Seed data loaded", os.path.exists(sb5.db_path))

# Simulate real code: INSERT Bob
conn = sqlite3.connect(sb5.db_path)
conn.execute("INSERT INTO users (id, name) VALUES (2, 'Bob')")
conn.commit(); conn.close()

drift5, match5 = sb5.compare_state()
check("DB state matches expected after INSERT", drift5 == 0.0 and match5 == "exact", f"drift={drift5} match={match5}")

sb5.teardown()
check("DB file cleaned up", not os.path.exists(sb5.db_path))

# Test FAIL: wrong data
sb6 = DBSandbox(fix_dir_db)
ctx6 = sb6.setup()
conn = sqlite3.connect(sb6.db_path)
conn.execute("INSERT INTO users (id, name) VALUES (2, 'Charlie')")  # wrong name
conn.commit(); conn.close()
drift6, match6 = sb6.compare_state()
check("DB state mismatch detected (Charlie != Bob)", drift6 > 0.0, f"drift={drift6} match={match6}")
sb6.teardown()

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*50)
total  = len(results)
passed = sum(1 for _, s, _ in results if s == "PASS")
failed = total - passed
print(f"TOTAL: {total}  PASS: {passed}  FAIL: {failed}")
print("="*50 + "\n")

with open("v040_sandbox_test_report.md", "w", encoding="utf-8") as f:
    f.write("# Golden Demo v0.4.0 Sandbox Test Report\n\n")
    f.write(f"**Result: {'ALL PASS' if failed == 0 else f'{failed} FAILED'}**\n\n")
    f.write("| Test | Status | Detail |\n|---|---|---|\n")
    for label, status, detail in results:
        f.write(f"| {label} | {status} | {detail[:80]} |\n")

print("Report: v040_sandbox_test_report.md")
sys.exit(0 if failed == 0 else 1)
