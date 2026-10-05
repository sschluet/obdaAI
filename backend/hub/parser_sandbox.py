"""Linux Landlock: the parser can read only its runtime and the one original."""

import ctypes
import os
import sys
from pathlib import Path

READ = (1 << 2) | (1 << 3)
EXEC = 1 << 0
WRITE = 1 << 1
ALL_FS = (1 << 15) - 1


class Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def restrict(source: Path, workdir: Path, *, office: bool = False) -> None:
    if sys.platform != "linux":
        return  # Development only; deployment parser is Linux with network_mode:none.
    libc = ctypes.CDLL(None, use_errno=True)
    create, add, apply = 444, 445, 446  # Linux generic x86_64 and aarch64 syscall numbers.
    abi = libc.syscall(create, 0, 0, 1)
    if abi < 3:
        raise ValueError("Parser benötigt Linux Landlock ABI >= 3")
    ruleset = Ruleset(ALL_FS)
    fd = libc.syscall(create, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0)
    if fd < 0:
        raise ValueError("Landlock nicht verfügbar")
    try:
        grants = [
            (Path("/usr"), READ | EXEC),
            (Path("/lib"), READ | EXEC),
            (Path("/lib64"), READ | EXEC),
            (Path("/etc/ld.so.cache"), 1 << 2),
            (Path("/etc/mime.types"), 1 << 2),
            (Path("/etc/fonts"), READ),
            (Path("/etc/passwd"), 1 << 2),
            (Path("/dev/null"), (1 << 2) | WRITE),
            (Path("/dev/urandom"), 1 << 2),
            (Path(sys.prefix), READ | EXEC),
            (Path(sys.base_prefix), READ | EXEC),
            (source, READ if source.is_dir() else 1 << 2),
            (workdir, ALL_FS),
        ]
        if office:
            # Debian's runtime directories are symlinks outside /usr. They hold
            # the immutable Office registry and bundled extension cache only.
            grants += [
                (Path("/etc/libreoffice"), READ),
                (Path("/var/lib/libreoffice"), READ),
                (Path("/var/spool/libreoffice"), READ),
                (Path("/etc/nsswitch.conf"), 1 << 2),
                (Path("/etc/group"), 1 << 2),
                # Only Unix socket entries, not arbitrary temporary files. The
                # private container tmpfs is short enough for sun_path and has
                # no input, credential or host socket mounts.
                (Path("/run/ipc"), READ | (1 << 9) | (1 << 5)),
            ]
        for path, access in grants:
            if not path.exists():
                continue
            parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(access, parent)
                if libc.syscall(add, fd, 1, ctypes.byref(rule), 0) < 0:
                    raise ValueError("Landlock-Pfadregel nicht verfügbar")
            finally:
                os.close(parent)
        if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.syscall(apply, fd, 0) < 0:
            raise ValueError("Parser-Dateisystemschutz nicht aktivierbar")
    finally:
        os.close(fd)
