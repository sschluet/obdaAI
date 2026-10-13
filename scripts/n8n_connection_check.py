"""Run only with human authorization for the exact inactive reviewed draft."""

import argparse
import json
from pathlib import Path

import httpx
from hub.n8n_check import CheckError, ConnectionCheck


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--approved-create", action="store_true")
    args = parser.parse_args()
    if args.key_file.is_symlink() or args.key_file.stat().st_mode & 0o077:
        raise SystemExit("Key file must be private and not a symlink")
    try:
        with httpx.Client(verify=True, trust_env=False) as client:
            result = ConnectionCheck(client, args.key_file.read_text().strip()).ensure(
                json.loads(args.review.read_text()), args.journal, approved=args.approved_create
            )
        print(json.dumps(result))
    except (CheckError, ValueError, KeyError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
