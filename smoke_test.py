#!/usr/bin/env python3
"""Quick API smoke test — login, zones, users, change-requests."""
import requests, json

BASE = "http://localhost:8000/api"
S = requests.Session()

# 1. Login as admin
r = S.post(f"{BASE}/auth/login", json={"username": "admin", "password": "admin123"})
assert r.status_code == 200, f"Login failed: {r.text}"
token = r.json()["access_token"]
S.headers.update({"Authorization": f"Bearer {token}"})
print("✓ Login as admin")

# 2. Zones
r = S.get(f"{BASE}/zones")
data = r.json()
print(f"✓ Zones: {data['total']} zones")
for z in data['items']:
    print(f"    {z['zone_name']} ({z['zone_type']}, {z['record_count']} records)")

# 3. Users
r = S.get(f"{BASE}/users")
data = r.json()
items = data.get('items', data) if isinstance(data, dict) else data
print(f"✓ Users: {len(items)} users")
for u in items:
    print(f"    {u['username']:12s} {u['role']:14s} active={u.get('is_active', True)}")

# 4. Create change request
r = S.post(f"{BASE}/change-requests", json={
    "action": "record_create",
    "zone_name": "ppv2.com",
    "summary": "Add test A record",
    "payload": {"name": "test", "type": "A", "ttl": 300, "data": "10.0.0.1"}
})
assert r.status_code == 201, f"Create CR failed: {r.text}"
cr = r.json()
print(f"✓ Change request created: #{cr['id']} status={cr['status']}")

# 5. List change requests
r = S.get(f"{BASE}/change-requests")
data = r.json()
print(f"✓ Change requests: {data['total']} total")
for cr in data['items']:
    print(f"    #{cr['id']} {cr['status']:10s} {cr['action']:15s} {cr['zone_name']}")

# 6. Login as approver and approve the request
r = S.post(f"{BASE}/auth/login", json={"username": "approver", "password": "appr123456"})
assert r.status_code == 200, f"Approver login failed: {r.text}"
S.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
print("✓ Login as approver")

cr_id = cr['id']
r = S.put(f"{BASE}/change-requests/{cr_id}/review", json={"action": "approve", "comment": "Approved — looks good"})
print(f"✓ Review response: id={r.json()['id']} status={r.json()['status']}")

# 7. Audit log
S.headers.update({"Authorization": f"Bearer {token}"})  # back to admin
r = S.get(f"{BASE}/audit")
data = r.json()
print(f"✓ Audit log: {data['total']} entries")

print("\n✅ ALL SMOKE TESTS PASSED")
