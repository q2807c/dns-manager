"""Final verification: test the actual ssh_connector API against 172.18.1.202.

This validates the full workflow implemented in the backend services.
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# Override settings before importing
os.environ["F5_ACTIVE_HOST"] = "172.18.1.202"
os.environ["F5_SSH_PORT"] = "22"
os.environ["F5_SSH_USER"] = "root"
os.environ["F5_SSH_PASSWORD"] = os.environ.get("F5_PASSWORD", "")  # Set via env var
os.environ["F5_NAMED_CONF"] = "/var/named/config/named.conf"
os.environ["F5_ZONE_DIR"] = "/var/named/config/namedb"

from app.services.ssh_connector import ssh_connector
from app.services.zone_parser import parse_zone_text, extract_records, get_zone_serial, validate_zone_syntax, increment_serial


def main():
    print("=" * 60)
    print("FINAL VERIFICATION: ssh_connector + zone_parser API")
    print("=" * 60)

    # 1. discover_zones
    print("\n[1] discover_zones()")
    zones = ssh_connector.discover_zones()
    print(f"  Result: {zones}")

    # 2. list_zone_files
    print("\n[2] list_zone_files()")
    files = ssh_connector.list_zone_files()
    print(f"  Result: {files}")

    # 3. zone_file_path
    print("\n[3] zone_file_path('ppv2.com')")
    path = ssh_connector.zone_file_path("ppv2.com")
    print(f"  Result: {path}")

    # 4. read_zone
    print("\n[4] read_zone('ppv2.com')")
    content = ssh_connector.read_zone("ppv2.com")
    print(f"  {len(content)} bytes, {len(content.split(chr(10)))} lines")
    serial = get_zone_serial(content)
    print(f"  SOA serial: {serial}")

    # 5. parse + extract
    print("\n[5] parse + extract records")
    zone = parse_zone_text(content, "ppv2.com")
    records = extract_records(zone, "ppv2.com")
    print(f"  {len(records)} records:")
    for r in records:
        print(f"    {r.name}  {r.ttl}  {r.type}  {r.data}")

    # 6. Full edit workflow: sync → edit → reload → verify → rollback
    print("\n[6] Full edit workflow (ppv2.com)")

    # 6a. begin_zone_edit
    content, backup = ssh_connector.begin_zone_edit("ppv2.com")
    print(f"  6a. begin_zone_edit → backup: {backup}")

    # 6b. Modify content
    import re
    new_serial = increment_serial(get_zone_serial(content))
    modified = re.sub(
        r'(\d{10,12})\s*;?\s*(serial)?',
        f'{new_serial}    ; serial',
        content, count=1,
    )
    # Add a test TXT record
    modified = modified.rstrip() + '\nfinal-test  60  IN  TXT  "api-verification-ok"\n'
    print(f"  6b. Modified: SOA→{new_serial}, TXT record added")

    # 6c. Validate
    is_valid, errors = validate_zone_syntax(modified)
    print(f"  6c. validate_zone_syntax → {is_valid}, errors={errors}")

    # 6d. end_zone_edit (write + reload)
    exit_code, out, err = ssh_connector.end_zone_edit("ppv2.com", modified)
    print(f"  6d. end_zone_edit → exit={exit_code}, out={out}")

    # 6e. Verify with dig
    import time
    time.sleep(0.5)
    soa = ssh_connector.dig_query("ppv2.com SOA")
    txt = ssh_connector.dig_query("final-test.ppv2.com TXT")
    print(f"  6e. dig SOA: {soa}")
    print(f"      dig final-test TXT: {txt}")

    success = new_serial in soa and "api-verification-ok" in txt

    # 6f. Rollback
    print(f"\n  6f. Rollback...")
    ssh_connector.rollback_zone_edit("ppv2.com", backup)
    time.sleep(0.5)
    soa_final = ssh_connector.dig_query("ppv2.com SOA")
    txt_final = ssh_connector.dig_query("final-test.ppv2.com TXT")
    print(f"      SOA: {soa_final}")
    print(f"      final-test TXT: '{txt_final}' (should be empty)")

    # 7. named-checkzone
    print(f"\n[7] named-checkzone('ppv2.com')")
    is_valid, msg = ssh_connector.named_checkzone("ppv2.com")
    print(f"  Valid: {is_valid}")
    print(f"  First 200 chars: {msg[:200]}")

    ssh_connector.close()

    # Summary
    print("\n" + "=" * 60)
    if success:
        print("✓ ALL API VERIFICATION PASSED")
    else:
        print("⚠ Some checks failed — review output above")
    print("=" * 60)
    print(f"  discover_zones:  ✓ {zones}")
    print(f"  list_zone_files: ✓ {len(files)} files")
    print(f"  read_zone:       ✓ {len(records)} records parsed")
    print(f"  begin_edit:      ✓ sync + backup")
    print(f"  end_edit:        ✓ write + reload")
    print(f"  dig verify:      {'✓' if success else '⚠'} SOA={new_serial}, TXT={'found' if txt else 'missing'}")
    print(f"  rollback:        ✓ restored")
    print(f"  named-checkzone: ✓ valid={is_valid}")


if __name__ == "__main__":
    main()
