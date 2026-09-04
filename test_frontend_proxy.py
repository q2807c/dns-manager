#!/usr/bin/env python3
"""Test frontend proxy: login → zones → records through Vite."""
import urllib.request, json, os

BASE = "http://localhost:3000/api"

def api(method, path, data=None, token=None):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = json.loads(e.read())
        return e.code, err

results = []

# 1. Login
s, r = api("POST", "/auth/login", {"username": "admin", "password": "admin123"})
token = r.get("access_token", "")
results.append(("Login", s == 200, f"status={s}, token={token[:20]}..."))

# 2. Me
s, r = api("GET", "/auth/me", token=token)
results.append(("Me", s == 200, f"role={r.get('role','?')}, user={r.get('username','?')}"))

# 3. Health
s, r = api("GET", "/health", token=None)
results.append(("Health", s == 200, f"host={r.get('f5_active_host','?')}"))

# 4. Zones
s, r = api("GET", "/zones?page=1&page_size=10", token=token)
results.append(("Zones", s == 200, f"total={r.get('total','?')}, zones={[z['zone_name'] for z in r.get('items',[])]}"))

# 5. Records for ppv2.com
s, r = api("GET", "/zones/ppv2.com/records?page=1&page_size=50", token=token)
results.append(("Records", s == 200, f"total={r.get('total','?')}, types={list(set(x['type'] for x in r.get('items',[])))}"))

# Print
for name, ok, detail in results:
    status = "✅" if ok else "❌"
    print(f"{status} {name}: {detail}")

print(f"\n{'ALL PASS' if all(ok for _, ok, _ in results) else 'SOME FAILED'}")
