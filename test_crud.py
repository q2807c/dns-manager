"""Test record CRUD against F5 via API."""
import urllib.request
import json

BASE = "http://localhost:8000"
ZONE = "ppv2.com"

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

def main():
    # Login
    _, login_data = api("POST", "/api/auth/login", {"username": "admin", "password": "admin123"})
    token = login_data["access_token"]

    # 1. CREATE a test TXT record
    print("=== 1. CREATE record ===")
    status, data = api("POST", f"/api/zones/{ZONE}/records",
        {"name": "test-api", "type": "TXT", "ttl": 300, "data": "hello from api"},
        token=token)
    if status == 201:
        print(f"  ✓ Created: {data['name']} {data['type']} {data['data']}")
    else:
        print(f"  ✗ {status}: {data.get('detail', str(data))[:100]}")
        return

    # 2. READ — verify it appears
    print("=== 2. VERIFY created ===")
    status, data = api("GET", f"/api/zones/{ZONE}/records?search=test-api", token=token)
    test_records = [r for r in data["items"] if r["name"] == "test-api"]
    if test_records:
        rec_id = test_records[0]["id"]
        print(f"  ✓ Found at index {rec_id}: {test_records[0]}")
    else:
        print("  ✗ Record not found after create")
        return

    # 3. UPDATE the record
    print("=== 3. UPDATE record ===")
    status, data = api("PUT", f"/api/zones/{ZONE}/records/{rec_id}",
        {"data": "updated from api"},
        token=token)
    if status == 200:
        print(f"  ✓ Updated")
    else:
        print(f"  ✗ {status}: {data.get('detail', str(data))[:100]}")

    # 4. VERIFY update
    print("=== 4. VERIFY update ===")
    status, data = api("GET", f"/api/zones/{ZONE}/records?search=test-api", token=token)
    updated = [r for r in data["items"] if r["name"] == "test-api"]
    if updated and "updated" in updated[0]["data"]:
        print(f"  ✓ Updated value confirmed: {updated[0]}")
    else:
        print(f"  ⚠ Record data: {updated}")

    # 5. DELETE the record
    print("=== 5. DELETE record ===")
    # Re-fetch the correct index since serial changed
    status, data = api("GET", f"/api/zones/{ZONE}/records?search=test-api", token=token)
    del_recs = [r for r in data["items"] if r["name"] == "test-api"]
    if del_recs:
        status, data = api("DELETE", f"/api/zones/{ZONE}/records/{del_recs[0]['id']}", token=token)
        print(f"  ✓ Deleted: {data}")
    else:
        print("  ✗ Record not found for deletion")

    # 6. VERIFY deletion
    print("=== 6. VERIFY deletion ===")
    status, data = api("GET", f"/api/zones/{ZONE}/records?search=test-api", token=token)
    remaining = [r for r in data["items"] if r["name"] == "test-api"]
    if not remaining:
        print("  ✓ Record successfully removed")
    else:
        print(f"  ✗ Record still present: {remaining}")

    # 7. Check audit log has entries
    print("=== 7. AUDIT ===")
    status, data = api("GET", "/api/audit?zone_name=ppv2.com", token=token)
    print(f"  ✓ {data['total']} audit entries for ppv2.com")
    for entry in data["items"][:5]:
        print(f"    [{entry['status']}] {entry['action']} by {entry['username']}")

    print("\n✅ CRUD test complete!")

if __name__ == "__main__":
    main()
