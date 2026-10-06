#!/usr/bin/python3
"""Root observer applies numeric source-only leases in a separate own chain."""

import ipaddress
import json
import secrets
import select
import socket
import struct
import subprocess
import sys
import time


def command(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=8)



def apply(plan):
    ids = []
    rules = {"iptables": set(), "ip6tables": set()}
    for row in plan[:200]:
        if row.get("kind") not in {"website", "smb", "obsidian", "sql", "nfs"}:
            continue
        accepted = []
        for raw, port in row.get("targets", [])[:32]:
            a = ipaddress.ip_address(raw)
            port = int(port)
            if (
                not 1 <= port <= 65535
                or a.is_loopback
                or a.is_link_local
                or a.is_multicast
                or a.is_unspecified
                or a.is_reserved
            ):
                continue
            if row["kind"] == "website" and (not a.is_global or port != 443):
                continue
            if row["kind"] == "nfs" and (a.is_global or port not in {111, 2049}):
                continue
            accepted.append((a, port))
            if row["kind"] == "nfs" and port == 111:
                # One bounded, fixed MOUNT v3 port lookup on this exact private peer.
                try:
                    with socket.create_connection((str(a), 111), timeout=2) as rpc:
                        xid = secrets.randbits(32)
                        payload = struct.pack(
                            "!14I", xid, 0, 2, 100000, 2, 3, 0, 0, 0, 0, 100005, 3, 6, 0
                        )
                        rpc.sendall(struct.pack("!I", 0x80000000 | len(payload)) + payload)
                        header = rpc.recv(4)
                        if len(header) == 4 and struct.unpack("!I", header)[0] & 0x7FFFFFFF == 28:
                            reply = b""
                            while len(reply) < 28:
                                part = rpc.recv(28 - len(reply))
                                if not part:
                                    break
                                reply += part
                            if len(reply) == 28:
                                words = struct.unpack("!7I", reply)
                                if words[:6] == (xid, 1, 0, 0, 0, 0) and 1 <= words[6] <= 65535:
                                    accepted.append((a, words[6]))
                except (OSError, ValueError):
                    pass
        if not accepted:
            continue
        ids.append(row["id"])
        for a, port in accepted:
            rules["iptables" if a.version == 4 else "ip6tables"].add((str(a), port))
    for program, targets in rules.items():
        command(program, "-N", "OBDAAI_SOURCES", check=False)
        command(program, "-F", "OBDAAI_SOURCES")
        for ip, port in sorted(targets):
            command(
                program,
                "-A",
                "OBDAAI_SOURCES",
                "-d",
                ip,
                "-p",
                "tcp",
                "--dport",
                str(port),
                "-j",
                "ACCEPT",
            )
        command(program, "-A", "OBDAAI_SOURCES", "-j", "RETURN")
        if command(program, "-C", "OBDAAI_APP", "-j", "OBDAAI_SOURCES", check=False).returncode:
            command(program, "-I", "OBDAAI_APP", "1", "-j", "OBDAAI_SOURCES")
    return ids


def clear():
    for program in ["iptables", "ip6tables"]:
        command(program, "-F", "OBDAAI_SOURCES", check=False)
        command(program, "-A", "OBDAAI_SOURCES", "-j", "RETURN", check=False)


def observe():
    # Import the application once. Repeated cold imports contend with inference
    # on a small VM and must not cause valid leases to oscillate.
    script = (
        "from hub.config import Settings\nfrom hub.db import session_factory\n"
        "from hub.source_network import requests_plan,grant\nimport json,sys,time\n"
        "factory=session_factory(Settings.from_env().database_url)\n"
        "while True:\n"
        " print(json.dumps(requests_plan(factory)),flush=True)\n"
        " line=sys.stdin.readline()\n"
        " if not line: break\n"
        " grant(factory,json.loads(line))\n"
        " time.sleep(2)\n"
    )
    process = subprocess.Popen(
        ["docker", "exec", "-i", "obdaai-api-1", "python", "-u", "-c", script],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True,
    )
    first = True
    try:
        while True:
            if not select.select([process.stdout], [], [], 60 if first else 10)[0]:
                raise TimeoutError("Source observer stalled")
            line = process.stdout.readline(1_000_000)
            if not line or not line.endswith("\n"):
                raise RuntimeError("Source observer exited")
            plan = json.loads(line)
            if not isinstance(plan, list):
                raise ValueError("Invalid source plan")
            ids = apply(plan)
            process.stdin.write(json.dumps(ids) + "\n")
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
            # Fail closed; clear only our own temporary chain, preserve all other rules.
            clear()
        time.sleep(2)
