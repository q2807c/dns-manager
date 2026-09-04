#!/usr/bin/env python3
"""End-to-end frontend CRUD test through Vite proxy on port 3000."""
import urllib.request, json

BASE = "http://localhost:3000/api"

def api(method, path, data=None, token=None):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

# Login
s, r = api("POST", "/auth/login", {"username":"admin","password":"admin123"})
token = r["access_token"]

print("=" * 60)
print("  End-to-End Frontend CRUD Test (via :3000 proxy)")
print("=" * 60)

# 1. Zone List
s, r = api("GET", "/zones?page=1&page_size=10", token=token)
print(f"\n1. Zone List: {s} | total={r['total']} zones={[z['zone_name'] for z in r['items']]}")

# 2. Record List
s, r = api("GET", "/zones/ppv2.com/records?page=1&page_size=50", token=token)
print(f"2. Record List: {s} | total={r['total']} serial={r['zone_serial']}")

# 3. Create Record
payload = {"name": "e2e-test", "type": "TXT", "ttl": 300, "data": "e2e-proxy-test"}
s, r = api("POST", "/zones/ppv2.com/records", payload, token)
print(f"3. Create Record: {s} | {r.get('detail','OK')}")

# 4. Verify creation
s, r = api("GET", "/zones/ppv2.com/records?search=e2e-test", token=token)
created = [x for x in r["items"] if x["name"] == "e2e-test"]
print(f"4. Verify Create: found={len(created)} | data={created[0]['data'] if created else 'N/A'}")

# 5. Update Record
if created:
    rid = created[0]["id"]
    payload = {"name": "e2e-test", "type": "TXT", "ttl": 600, "data": "e2e-proxy-updated"}
    s, r = api("PUT", f"/zones/ppv2.com/records/{rid}", payload, token)
    print(f"5. Update Record: {s} | {r.get('detail','OK')}")

# 6. Verify update
s, r = api("GET", "/zones/ppv2.com/records?search=e2e-test", token=token)
updated = [x for x in r["items"] if x["name"] == "e2e-test"]
print(f"6. Verify Update: ttl={updated[0]['ttl'] if updated else 'N/A'} | data={updated[0]['data'] if updated else 'N/A'}")

# 7. Delete Record
if created:
    s, r = api("DELETE", f"/zones/ppv2.com/records/{rid}", token=token)
    print(f"7. Delete Record: {s} | {r.get('detail','OK')}")

# 8. Audit log
s, r = api("GET", "/audit?page=1&page_size=5", token=token)
print(f"8. Audit Log: {s} | total={r['total']}")

# 9. Users
s, r = api("GET", "/users", token=token)
print(f"9. Users: {s} | total={r.get('total','?')}")

print("\n" + "=" * 60)
print("  ALL TESTS COMPLETE")
print("=" * 60)
