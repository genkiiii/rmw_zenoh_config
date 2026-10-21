#!/usr/bin/env python3
"""Validate local deployment values without executing the env file as shell code."""
import ipaddress
from pathlib import Path
import shlex
import sys


def read_deployment(path):
    values = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, text = line.partition("=")
        key = key.strip()
        if not separator or key not in ("ROLE", "SERVER", "ROS_DOMAIN_ID"):
            raise ValueError(f"Line {number}: only ROLE/SERVER/ROS_DOMAIN_ID are supported")
        if key in values:
            raise ValueError(f"Duplicate key: {key}")
        words = shlex.split(text, comments=True)
        if len(words) != 1:
            raise ValueError(f"Line {number}: expected one value")
        values[key] = words[0]
    if set(values) != {"ROLE", "SERVER", "ROS_DOMAIN_ID"}:
        raise ValueError("ROLE, SERVER and ROS_DOMAIN_ID are all required")
    if values["ROLE"] not in ("central", "vehicle", "control"):
        raise ValueError("ROLE must be central, vehicle or control")
    values["SERVER"] = str(ipaddress.IPv4Address(values["SERVER"]))
    domain = values["ROS_DOMAIN_ID"]
    if not domain.isascii() or not domain.isdecimal() or not 0 <= int(domain) <= 232:
        raise ValueError("ROS_DOMAIN_ID must be an integer between 0 and 232")
    values["ROS_DOMAIN_ID"] = str(int(domain))
    return values


if __name__ == "__main__":
    try:
        for key, value in read_deployment(sys.argv[1]).items():
            print(f"{key}={shlex.quote(value)}")
    except (OSError, ValueError) as error:
        print(f"Invalid deployment env: {error}", file=sys.stderr)
        sys.exit(1)
