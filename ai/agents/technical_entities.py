"""Deterministic, explainable technical-token extraction for support tickets."""
import ipaddress
import re

RULE_VERSION = "technical-entities-rules-1.0"

PATTERNS = {
    "url": re.compile(r"https?://[^\s<>'\"]+", re.I),
    "ipv4": re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}\b"),
    "ipv6": re.compile(r"(?<![\w:])(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{1,4}(?![\w:])", re.I),
    "file_path": re.compile(r"(?:[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]+|/(?:[\w.\-]+/)+[\w.\-]+)"),
    "error_code": re.compile(r"\b(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b"),
    "version": re.compile(r"\b(?:v(?:ersion)?\s*)?\d+\.\d+(?:\.\d+){0,2}\b", re.I),
    "date": re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"),
    "time": re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[AP]M)?\b", re.I),
    "host_name": re.compile(r"\b(?:server|host|hostname)\s*[:=]?\s*([a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?)\b", re.I),
    "command": re.compile(r"(?m)(?:^|[> `$])((?:ipconfig|ping|tracert|nslookup|netsh|systemctl|kubectl|docker|git|python|npm)\b[^\r\n]*)", re.I),
}
OPERATING_SYSTEMS = re.compile(r"\b(?:Windows\s+(?:10|11|Server(?:\s+\d{4})?)|macOS(?:\s+\d+(?:\.\d+)*)?|Ubuntu(?:\s+\d+(?:\.\d+)*)?|RHEL\s*\d+|Android\s*\d*|iOS\s*\d*)\b", re.I)
DEVICE_TYPES = re.compile(r"\b(laptop|desktop|workstation|server|mobile|phone|tablet|router|firewall)\b", re.I)
SERVICES = re.compile(r"\b(VPN|Wi-?Fi|email|Outlook|SAP|database|network|DNS|DHCP|Active Directory|cloud)\b", re.I)
APPLICATIONS = re.compile(r"\b(Microsoft Teams|Outlook|SAP|Chrome|Microsoft Edge|Firefox|Docker Desktop|Cisco AnyConnect|GlobalProtect)\b", re.I)
SECURITY_INDICATORS = re.compile(r"\b(phishing|malware|ransomware|unauthorized access|credential compromise|data breach|suspicious login)\b", re.I)
TROUBLESHOOTING = re.compile(r"(?i)\b((?:tried|attempted|already|restarted?|cleared|reinstalled|ran)\b[^.!?\r\n]{3,240})")


def extract_technical_entities(text: str, source: str = "description") -> list[dict]:
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, match: re.Match, confidence: float = 0.98) -> None:
        raw = match.group(1) if match.lastindex else match.group(0)
        raw = raw.strip().rstrip(".,;)")
        normalized = raw.lower() if kind in {"affected_service", "device_type"} else raw
        if kind == "host_name" and normalized.casefold() in {"is", "was", "has", "not", "down", "unavailable"}: return
        if kind in {"ipv4", "ipv6"}:
            try: normalized = str(ipaddress.ip_address(raw))
            except ValueError: return
        if kind == "version":
            try: ipaddress.ip_address(raw)
            except ValueError: pass
            else: return
        key = (kind, normalized.casefold())
        if key in seen: return
        seen.add(key)
        start = match.start(1) if match.lastindex else match.start()
        found.append({"entity_type": kind, "raw_value": raw, "normalized_value": normalized,
                      "source": source, "extraction_method": RULE_VERSION, "confidence": confidence,
                      "start_offset": start, "end_offset": start + len(raw), "validation_status": "extracted"})

    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(text or ""): add(kind, match)
    for match in OPERATING_SYSTEMS.finditer(text or ""): add("operating_system", match, .96)
    for match in DEVICE_TYPES.finditer(text or ""): add("device_type", match, .90)
    for match in SERVICES.finditer(text or ""): add("affected_service", match, .90)
    for match in APPLICATIONS.finditer(text or ""): add("application_name", match, .94)
    for match in SECURITY_INDICATORS.finditer(text or ""): add("security_indicator", match, .96)
    for match in TROUBLESHOOTING.finditer(text or ""): add("troubleshooting_attempt", match, .84)
    return sorted(found, key=lambda item: (item["start_offset"], item["entity_type"]))
