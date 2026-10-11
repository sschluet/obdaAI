#!/usr/bin/python3
"""Root observer permits only numeric endpoints from enabled human integration profiles."""

import ipaddress
import json
import select
import subprocess
import sys
import time


def command(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=8)


def valid_address(value):
    a = ipaddress.ip_address(value)
    if a.version == 6 and a.ipv4_mapped:
        return valid_address(str(a.ipv4_mapped))
    return not (
        a.is_loopback
        or a.is_link_local
        or a.is_multicast
        or a.is_unspecified
        or a.is_reserved
        or str(a) in {"100.100.100.200", "fd00:ec2::254"}
    )


def apply(plan):
    ids = []
    rules = {"iptables": set(), "ip6tables": set()}
    for row in plan[:200]:
        if row.get("kind") not in {"home_assistant", "paperless", "mcp", "unifi", "ssh"}:
            continue
        accepted = []
        for raw, port in row.get("targets", [])[:32]:
            a = ipaddress.ip_address(raw)
            port = int(port)
            if not 1 <= port <= 65535 or not valid_address(raw):
                continue
            accepted.append((a, port))
        if not accepted:
            continue
        ids.append(row["id"])
        for a, port in accepted:
            rules["iptables" if a.version == 4 else "ip6tables"].add((str(a), port))
    for program, targets in rules.items():
        command(program, "-N", "OBDAAI_INTEGRATIONS", check=False)
        command(program, "-F", "OBDAAI_INTEGRATIONS")
        for ip, port in sorted(targets):
            command(
                program,
                "-A",
                "OBDAAI_INTEGRATIONS",
                "-d",
                ip,
                "-p",
                "tcp",
                "--dport",
                str(port),
                "-j",
                "ACCEPT",
            )
        command(program, "-A", "OBDAAI_INTEGRATIONS", "-j", "RETURN")
        if command(
            program, "-C", "OBDAAI_APP", "-j", "OBDAAI_INTEGRATIONS", check=False
        ).returncode:
            command(program, "-I", "OBDAAI_APP", "1", "-j", "OBDAAI_INTEGRATIONS")
    return ids


def clear():
    for program in ["iptables", "ip6tables"]:
        command(program, "-F", "OBDAAI_INTEGRATIONS", check=False)
        command(program, "-A", "OBDAAI_INTEGRATIONS", "-j", "RETURN", check=False)


def observe():
    # Import the application once. Repeated cold imports contend with inference
    # on a small VM and must not cause valid leases to oscillate.
    script = (
        "from hub.config import Settings\nfrom hub.db import session_factory\n"
        "from hub.integration_transport import requests_plan\nimport json,sys,time\n"
        "cfg=Settings.from_env()\nfactory=session_factory(cfg.database_url)\n"
        "while True:\n"
        " print(json.dumps(requests_plan(factory,cfg)),flush=True)\n"
        " line=sys.stdin.readline()\n"
        " if not line: break\n"
        " time.sleep(2)\n"
    )
    process = subprocess.Popen(
        ["docker", "exec", "-i", "obdaai-api-1", "python", "-u", "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    first = True
    previous_plan, applied_ids = None, []
    try:
        while True:
            if not select.select([process.stdout], [], [], 60 if first else 10)[0]:
                raise TimeoutError("Integration observer stalled")
            line = process.stdout.readline(1_000_000)
            if not line or not line.endswith("\n"):
                raise RuntimeError("Integration observer exited")
            plan = json.loads(line)
            if not isinstance(plan, list):
                raise ValueError("Invalid integration plan")
            if plan != previous_plan or any(
                command(program, "-S", "OBDAAI_INTEGRATIONS", check=False).returncode
                for program in ("iptables", "ip6tables")
            ):
                applied_ids = apply(plan)
                previous_plan = plan
            else:
                # Preserve leases without periodically flushing live rules. A
                # separate egress reload may remove the hook, so check it again.
                for program in ("iptables", "ip6tables"):
                    if command(
                        program, "-C", "OBDAAI_APP", "-j", "OBDAAI_INTEGRATIONS", check=False
                    ).returncode:
                        command(program, "-I", "OBDAAI_APP", "1", "-j", "OBDAAI_INTEGRATIONS")
            process.stdin.write(json.dumps(applied_ids) + "\n")
            process.stdin.flush()
            first = False
    finally:
        process.stdin.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    if sys.argv[1:] == ["--clear"]:
        clear()
        sys.exit(0)
    while True:
        try:
            observe()
        except Exception:
            # Fail closed; clear only our own integration chain, preserve all other rules.
            clear()
        time.sleep(2)
