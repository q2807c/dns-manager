"""Quick API integration test against running backend."""
import urllib.request
import json

BASE = "http://localhost:8000"

def api(method, path, data=None, token=None):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def test():
    # 1. Login
    print("=== 1. LOGIN ===")
    status, data = api("POST", "/api/auth/login", {"username": "admin", "password": "admin123"})
    assert status == 200, f"Login failed: {data}"
    token = data["access_token"]
    user = data["user"]
    print(f"  ✓ {user['username']} ({user['role']})")

    # 2. Get me
    print("=== 2. GET /api/auth/me ===")
    status, data = api("GET", "/api/auth/me", token=token)
    assert status == 200
    print(f"  ✓ username={data['username']}")

    # 3. List zones (from DB seed — no F5 needed)
    print("=== 3. GET /api/zones ===")
    status, data = api("GET", "/api/zones", token=token)
    assert status == 200
    print(f"  ✓ total={data['total']}, items={len(data['items'])}")
    for z in data["items"]:
        print(f"    - {z['zone_name']} ({z['zone_type']})")

    # 4. List records (needs F5 SSH)
    print("=== 4. GET /api/zones/ppv2.com/records ===")
    status, data = api("GET", "/api/zones/ppv2.com/records?page=1&page_size=50", token=token)
    if status == 200:
        print(f"  ✓ total={data['total']}, serial={data.get('zone_serial')}")
        for r in data["items"][:5]:
            print(f"    - {r['name']:20s} {r['type']:6s} {r['data'][:40]}")
    else:
        print(f"  ⚠ {status}: {data.get('detail', 'unknown')[:80]}")

    # 5. List audit logs
    print("=== 5. GET /api/audit ===")
    status, data = api("GET", "/api/audit", token=token)
    assert status == 200
    print(f"  ✓ total={data['total']}")

    print("\n✅ All tests passed!")

if __name__ == "__main__":
    test()
