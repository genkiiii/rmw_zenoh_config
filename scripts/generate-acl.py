#!/usr/bin/env python3
"""Generate a startup ACL override for rmw_zenoh Humble 0.1.11."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import socket
import subprocess
import sys


def detect_interface(server):
    address = str(ipaddress.IPv4Address(server))
    result = subprocess.run(
        ["ip", "-j", "-4", "route", "get", address],
        check=True, capture_output=True, text=True, timeout=5)
    routes = json.loads(result.stdout)
    if len(routes) != 1:
        raise ValueError("Expected one route to SERVER")
    route = routes[0]
    interface = route.get("dev", "")
    if route.get("type") in ("local", "unreachable", "blackhole", "prohibit"):
        raise ValueError("SERVER must have a reachable, non-local route")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", interface) or interface == "lo":
        raise ValueError("Cannot resolve a non-loopback interface")
    # Also reject local addresses routed through non-loopback devices.
    local = subprocess.run(
        ["ip", "-j", "-4", "addr", "show"],
        check=True, capture_output=True, text=True, timeout=5)
    if any(a.get("local") == address for link in json.loads(local.stdout)
           for a in link.get("addr_info", [])):
        raise ValueError("SERVER is a local address; use this profile on endpoint PCs")
    socket.if_nametoindex(interface)
    return interface


def normalize_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError("Profile must be an object")
    # Preserve compatibility with already installed action-only profiles.
    if set(profile) == {"deny_actions"}:
        profile = {"deny": {"actions": profile["deny_actions"]}}
    if not profile or set(profile) - {"allow", "deny"}:
        raise ValueError("Profile must contain allow/deny sections")
    normalized = {}
    for mode in ("allow", "deny"):
        section = profile.get(mode, {})
        if not isinstance(section, dict) or set(section) - {"topics", "services", "actions"}:
            raise ValueError("Sections support only topics/services/actions")
        normalized[mode] = {}
        for kind in ("topics", "services", "actions"):
            names = section.get(kind, [])
            if not isinstance(names, list):
                raise ValueError(f"{mode}.{kind} must be a list")
            for name in names:
                if not isinstance(name, str) or not re.fullmatch(r"(?:/[A-Za-z_][A-Za-z0-9_]*)+", name):
                    raise ValueError("ROS names must be absolute, with no wildcards")
            normalized[mode][kind] = sorted(set(names))
    if any(normalized["allow"].values()):
        raise ValueError("allow lists are reserved and must be empty in this release")
    return normalized


def build_acl(profile, domain, interface):
    if not str(domain).isdigit():
        raise ValueError("DOMAIN_ID must be a nonnegative integer")
    normalized = normalize_profile(profile)
    denied = normalized["deny"]
    names = set(denied["topics"] + denied["services"])
    for action in denied["actions"]:
        for suffix in ("send_goal", "get_result", "cancel_goal", "feedback", "status"):
            names.add(action + "/_action/" + suffix)
    if not names:
        return None
    data_keys, graph_keys = [], []
    for name in sorted(names):
        data_keys.append(f"{domain}/{name.lstrip('/')}/*/*")
        graph_keys.append(f"@ros2_lv/{domain}/" + "*/" * 7
                          + name.replace("/", "%") + "/*/*/*")
    return {
        "enabled": True,
        "default_permission": "allow",
        "rules": [
            {"id": "deny-action-data", "permission": "deny",
             "flows": ["ingress", "egress"],
             "messages": ["put", "delete", "declare_subscriber", "query", "reply", "declare_queryable"],
             "key_exprs": sorted(set(data_keys))},
            {"id": "deny-action-discovery", "permission": "deny",
             "flows": ["ingress", "egress"],
             "messages": ["liveliness_token", "liveliness_query", "declare_liveliness_subscriber"],
             "key_exprs": sorted(set(graph_keys))}
        ],
        "subjects": [{"id": "central-route", "interfaces": [interface]}],
        "policies": [{"subjects": ["central-route"],
                      "rules": ["deny-action-data", "deny-action-discovery"]}]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()
    profile = json.loads(Path(args.profile).read_text())
    if build_acl(profile, args.domain, "validation-only") is None:
        print("ACL: empty profile; no generated restrictions", file=sys.stderr)
        return
    interface = detect_interface(args.server)
    acl = build_acl(profile, args.domain, interface)
    print(f"ACL: SERVER={args.server}, interface={interface}, profile={args.profile}", file=sys.stderr)
    print("access_control=" + json.dumps(acl, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"ACL generation failed; router will not start: {error}", file=sys.stderr)
        sys.exit(1)
