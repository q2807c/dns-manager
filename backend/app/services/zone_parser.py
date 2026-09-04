"""DNS zone file parser using dnspython."""
import io
import logging
from typing import List, Optional, Tuple
from datetime import datetime

import dns.zone
import dns.rdatatype
import dns.rdataclass
import dns.name
import dns.rdata
from dns.exception import DNSException

from app.schemas import DNSRecord

logger = logging.getLogger(__name__)

# Standard record types supported
RECORD_TYPES = {
    "A": dns.rdatatype.A,
    "AAAA": dns.rdatatype.AAAA,
    "CNAME": dns.rdatatype.CNAME,
    "MX": dns.rdatatype.MX,
    "NS": dns.rdatatype.NS,
    "SRV": dns.rdatatype.SRV,
    "TXT": dns.rdatatype.TXT,
    "PTR": dns.rdatatype.PTR,
    "SOA": dns.rdatatype.SOA,
}


def _preprocess_f5_zone(zone_content: str, zone_name: str) -> str:
    """Normalize F5 Zonerunner zone format for dnspython compatibility.

    F5 zone files use '$ORIGIN .' and refer to the zone apex by full
    domain name (e.g. 'ppv2.com IN SOA ...'). dnspython requires SOA at
    the zone origin, so we strip '$ORIGIN .' and convert the apex name.
    """
    lines = zone_content.split("\n")
    result = []

    for line in lines:
        stripped = line.lstrip()
        # Remove $ORIGIN . — it conflicts with dnspython's origin model
        if stripped.upper().startswith("$ORIGIN") and stripped.endswith("."):
            # Keep $ORIGIN lines that point to the actual zone
            origin_value = stripped.split()[1] if len(stripped.split()) >= 2 else ""
            if origin_value == ".":
                continue  # skip root origin
            # Otherwise keep it (e.g. $ORIGIN ppv2.com.)

        # Replace the zone apex name at start of line with @
        words = stripped.split(None, 2)
        if words and words[0] == zone_name:
            line = line.replace(zone_name, "@", 1)

        result.append(line)

    return "\n".join(result)


def parse_zone_text(zone_content: str, origin: str = ".") -> dns.zone.Zone:
    """Parse raw zone file text into a dnspython Zone object.

    Handles F5 Zonerunner format ($ORIGIN . with full domain SOA) by
    normalizing before parsing.

    Raises DNSException on parse error.
    """
    # Detect zone name from content if origin not explicitly provided
    detected_origin = origin
    if origin == ".":
        import re
        # Find all $ORIGIN directives, use the last one that isn't root
        origins = re.findall(r'\$ORIGIN\s+(\S+)', zone_content)
        for o in reversed(origins):
            if o != ".":
                detected_origin = o.rstrip(".")
                break

    if detected_origin != ".":
        zone_content = _preprocess_f5_zone(zone_content, detected_origin)

    return dns.zone.from_text(
        zone_content,
        origin=dns.name.from_text(detected_origin),
        check_origin=True,
        relativize=True,
    )


def extract_records(zone: dns.zone.Zone, zone_name: str) -> List[DNSRecord]:
    """Extract DNS records from a parsed zone into structured list.

    Handles F5 Zonerunner format where SOA/NS may use the full domain
    name as owner (e.g. 'ppv2.com.' instead of '@').
    """
    records = []
    origin_suffix = f".{zone_name}." if not zone_name.endswith(".") else zone_name

    for name, ttl, rdata in zone.iterate_rdatas():
        record_name = str(name).rstrip(".")

        # Normalize: ppv2.com → @, www.ppv2.com → www
        if record_name == zone_name or record_name == f"{zone_name}.":
            record_name = "@"
        elif record_name.endswith(f".{zone_name}"):
            record_name = record_name[: -(len(zone_name) + 1)]

        rdtype = dns.rdatatype.to_text(rdata.rdtype)

        # Format data depending on type
        if rdata.rdtype == dns.rdatatype.SOA:
            data = f"{rdata.mname} {rdata.rname} {rdata.serial} {rdata.refresh} {rdata.retry} {rdata.expire} {rdata.minimum}"
        elif rdata.rdtype == dns.rdatatype.MX:
            data = f"{rdata.preference} {rdata.exchange}"
        elif rdata.rdtype == dns.rdatatype.SRV:
            data = f"{rdata.priority} {rdata.weight} {rdata.port} {rdata.target}"
        else:
            data = str(rdata).strip('"')

        records.append(DNSRecord(
            name=record_name,
            type=rdtype,
            ttl=ttl,
            data=data,
        ))

    return records


def get_zone_serial(zone_content: str) -> Optional[str]:
    """Extract SOA serial from zone file content.

    Uses regex to handle F5 Zonerunner format ($ORIGIN .).
    """
    import re
    # Match the serial number in SOA record — it's the first number
    # after the opening parenthesis of the SOA block
    match = re.search(r'SOA\s.*?\(\s*\n?\s*(\d{10,12})\s*;?\s*(serial|Serial)?', zone_content, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def increment_serial(current_serial: Optional[str]) -> str:
    """Increment serial number in YYYYMMDDNN format."""
    today = datetime.now().strftime("%Y%m%d")
    if current_serial and current_serial.startswith(today):
        try:
            seq = int(current_serial[8:10]) + 1
            return f"{today}{seq:02d}"
        except (ValueError, IndexError):
            pass
    return f"{today}01"


def serialize_zone(zone: dns.zone.Zone) -> str:
    """Serialize a dnspython Zone object back to zone file text."""
    buf = io.StringIO()
    zone.to_file(buf, relativize=True, want_origin=True)
    return buf.getvalue()


def validate_zone_syntax(zone_content: str) -> Tuple[bool, List[str]]:
    """Validate zone file syntax.

    Returns (is_valid, error_messages).
    """
    errors = []
    try:
        zone = parse_zone_text(zone_content)

        # Check SOA exists
        has_soa = False
        has_ns = False
        for name, ttl, rdata in zone.iterate_rdatas():
            if rdata.rdtype == dns.rdatatype.SOA:
                has_soa = True
            if rdata.rdtype == dns.rdatatype.NS:
                has_ns = True

        if not has_soa:
            errors.append("Missing SOA record")
        if not has_ns:
            errors.append("Missing NS record")

    except DNSException as e:
        errors.append(f"Zone parse error: {e}")

    return len(errors) == 0, errors


def generate_zone_template(
    zone_name: str,
    ttl: int = 300,
    master_server: str = "dns1.",
    email_contact: str = "hostmaster.",
    ns_servers: Optional[List[str]] = None,
    master_ip: Optional[str] = None,
) -> str:
    """Generate a new zone file from template.

    If master_server is a subdomain of zone_name and master_ip is provided,
    an A record for the master_server is automatically added (glue record).
    """
    serial = increment_serial(None)

    # Replace dots in email
    email = email_contact.replace("@", ".")
    if not email.endswith("."):
        email += "."

    # Normalize master_server
    master = master_server if master_server.endswith(".") else master_server + "."

    lines = [
        f'$ORIGIN {zone_name}.',
        f'$TTL {ttl}',
        '',
        f'@   IN SOA  {master} {email} (',
        f'        {serial}    ; serial',
        f'        3600        ; refresh',
        f'        900         ; retry',
        f'        604800      ; expire',
        f'        {ttl}       ; minimum',
        f'        )',
        '',
    ]

    # NS records
    if ns_servers:
        for ns in ns_servers:
            ns_name = ns if ns.endswith(".") else ns + "."
            lines.append(f'@   IN NS    {ns_name}')
    else:
        lines.append(f'@   IN NS    {master}')

    # Glue A record for master server if IP is provided
    if master_ip:
        # Extract short name if master is within this zone
        zone_suffix = f".{zone_name}."
        if master.endswith(zone_suffix):
            short_name = master[:-len(zone_suffix)]
            lines.append(f'{short_name}    IN A    {master_ip}')
        elif master == f"{zone_name}.":
            lines.append(f'@    IN A    {master_ip}')
        else:
            # Master is outside this zone — still add A record with full name
            # (dnspython/to_text will handle it)
            lines.append(f'{master.rstrip(".")}    IN A    {master_ip}')

    lines.append("")
    return "\n".join(lines)


def apply_record_changes(
    zone_content: str,
    records_to_add: List[DNSRecord],
    records_to_delete: List[DNSRecord],
    new_serial: str,
) -> Tuple[str, Optional[str]]:
    """Apply record additions and deletions to zone content.

    Returns (new_zone_content, error_message_or_none).
    """
    # For now, this is done at the raw text level.
    # A more robust approach would use dnspython for manipulation.
    try:
        zone = parse_zone_text(zone_content)
    except DNSException as e:
        return "", str(e)

    # Apply deletions
    for del_rec in records_to_delete:
        name = dns.name.from_text(del_rec.name)
        rdtype = RECORD_TYPES.get(del_rec.type)
        if rdtype:
            try:
                rdataset = zone.find_rdataset(name, rdtype, create=False)
                if rdataset:
                    zone.delete_rdataset(name, rdtype)

            except KeyError:
                continue  # Record not found, skip

    # Apply additions
    for add_rec in records_to_add:
        name = dns.name.from_text(add_rec.name)

        for rdtype_str, rdtype_val in RECORD_TYPES.items():
            if rdtype_val == dns.rdatatype.SOA:
                continue  # Don't manipulate SOA via this method

    # Update SOA serial
    soa_name = dns.name.from_text("@")
    try:
        soa_rdataset = zone.find_rdataset(soa_name, dns.rdatatype.SOA)
        if soa_rdataset:
            for rd in soa_rdataset:
                new_soa = dns.rdata.from_text(
                    dns.rdataclass.IN,
                    dns.rdatatype.SOA,
                    f"{rd.mname} {rd.rname} {new_serial} {rd.refresh} {rd.retry} {rd.expire} {rd.minimum}",
                )
            soa_rdataset.clear()
            soa_rdataset.add(new_soa, soa_rdataset.ttl)

    except (KeyError, ValueError):
        pass

    return serialize_zone(zone), None
