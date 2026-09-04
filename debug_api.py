#!/usr/bin/env python3
"""Debug zones API and users API"""
import requests, json

BASE = "http://localhost:8000/api"

# Login
r = requests.post(f"{BASE}/auth/login", json={"username": "admin", "password": "admin123"})
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Test zones
print("=== Zones (default) ===")
r = requests.get(f"{BASE}/zones", headers=headers)
print(f"Status: {r.status_code}")
data = r.json()
print(f"Type: {type(data)}, keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
if isinstance(data, dict):
    print(f"total: {data.get('total')}, items count: {len(data.get('items', []))}")
    for z in data.get('items', []):
        print(f"  id={z['id']} name={z['zone_name']}")

print("\n=== Zones (page_size=200) ===")
r = requests.get(f"{BASE}/zones?page_size=200", headers=headers)
data = r.json()
print(f"total: {data.get('total')}, items count: {len(data.get('items', []))}")

# Test users
print("\n=== Users ===")
r = requests.get(f"{BASE}/users", headers=headers)
data = r.json()
print(f"Status: {r.status_code}")
if isinstance(data, dict):
    items = data.get('items', data)
    print(f"Count: {len(items) if isinstance(items, list) else 'not list'}")
    for u in (items if isinstance(items, list) else []):
        print(f"  {u['username']} role={u['role']} zone_access={u.get('zone_access', 'MISSING')}")

print("\n=== User ops details ===")
r = requests.get(f"{BASE}/users", headers=headers)
users = r.json().get('items', [])
ops_user = next((u for u in users if u['username'] == 'ops'), None)
if ops_user:
    print(f"zone_access: {ops_user.get('zone_access')}")
    print(f"zone_access type: {type(ops_user.get('zone_access'))}")
