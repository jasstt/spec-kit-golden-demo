# HTTP Proxy Injection Test

## Scope

This test verifies the v0.4.2 HTTP proxy injection behavior for plain HTTP calls and explicitly documents the HTTPS limitation.

## Fixture

- Vector type: `http`
- Fixture route: `GET http://api.example.com/users`
- Expected response: `[{"id": 1, "name": "Ada"}]`
- Expected call record:

```json
[
  {
    "method": "GET",
    "host": "api.example.com",
    "path": "/users",
    "body": ""
  }
]
```

## Plain HTTP Test

The real implementation used an external hostname directly, with no fixture-aware code:

```python
import json
import requests

resp = requests.get("http://api.example.com/users", timeout=5)
print(json.dumps(resp.json()))
```

Golden Demo injected the proxy env vars only into the subprocess env copy:

```text
HTTP_PROXY=http://127.0.0.1:<fixture_port>
HTTPS_PROXY=http://127.0.0.1:<fixture_port>
NODE_TLS_REJECT_UNAUTHORIZED=0
PYTHONHTTPSVERIFY=0
```

Result:

```text
Golden Demo v0.4.2
PASS: 1  FAIL: 0  ERROR: 0  UNSUPPORTED: 0  SNAPSHOT_PENDING: 0
Drift Score: 0.00
[OK] No drift detected.
```

Drift report excerpt:

```text
- Status: PASS
- Golden Output: [{'id': 1, 'name': 'Ada'}]
- Real Output: [{'id': 1, 'name': 'Ada'}]
- Drift: 0.0 (output:exact + state:exact)
```

This confirms that `requests.get("http://api.example.com/users")` was routed through the fixture proxy as an absolute-form request and matched by host/path. The test used an external hostname, not `localhost` or `127.0.0.1`, so client-side localhost proxy bypass rules did not apply.

## HTTPS Limitation Test

The same real implementation was changed only from `http://` to `https://`:

```python
import json
import requests

resp = requests.get("https://api.example.com/users", timeout=5, verify=False)
print(json.dumps(resp.json()))
```

Result:

```text
Golden Demo v0.4.2
PASS: 0  FAIL: 0  ERROR: 1  UNSUPPORTED: 0  SNAPSHOT_PENDING: 0
Drift Score: 0.00
```

Drift report excerpt:

```text
- Status: ERROR
- Drift: N/A (error)
- Notes: ... self._prepare_proxy(conn) ...
         ... self._tunnel() ...
         OSError: Tunnel connection failed: 501 Not Implemented
         urllib3.exceptions.ProxyError: ('Unable to connect to proxy', ...)
```

This is expected. HTTPS clients use `CONNECT api.example.com:443`, then encrypt the inner request. A standard forward proxy fixture cannot see or match `/users` without MITM certificate handling. Golden Demo v0.4.2 intentionally documents this as out of scope.
