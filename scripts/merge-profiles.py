#!/usr/bin/env python3
"""Validate and merge one or more selected device profiles before installation."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

spec = importlib.util.spec_from_file_location("acl", Path(__file__).with_name("generate-acl.py"))
acl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acl)


def merge_profiles(directory, device="", devices=""):
    if device and devices:
        raise ValueError("Specify DEVICE or DEVICES, not both")
    names = devices.split() if devices else [device]
    if not names or any(not re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in names):
        raise ValueError("DEVICE or DEVICES is required; use profile names without paths")
    result = {mode: {kind: [] for kind in ("topics", "services", "actions")}
              for mode in ("deny", "allow")}
    for name in names:
        profile = acl.normalize_profile(json.loads((Path(directory) / (name + ".json")).read_text()))
        for mode in result:
            for kind in result[mode]:
                result[mode][kind] = sorted(set(result[mode][kind] + profile[mode][kind]))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--device", default="")
    parser.add_argument("--devices", default="")
    args = parser.parse_args()
    try:
        print(json.dumps(merge_profiles(args.directory, args.device, args.devices), indent=2))
    except (OSError, ValueError) as error:
        print(f"Profile selection failed: {error}", file=sys.stderr)
        sys.exit(1)
