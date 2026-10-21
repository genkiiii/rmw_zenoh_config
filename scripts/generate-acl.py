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


def build_acl(profile, domain, interface):
    if not str(domain).isdigit():
        raise ValueError("DOMAIN_ID must be a nonnegative integer")
    if set(profile) != {"deny_actions"} or not isinstance(profile["deny_actions"], list):
        raise ValueError("Profile must contain only deny_actions: [absolute action names]")
    actions = profile["deny_actions"]
    if not actions:
        raise ValueError("deny_actions must not be empty")
    data_keys, graph_keys = [], []
    for action in actions:
        if not isinstance(action, str) or not re.fullmatch(r"(?:/[A-Za-z_][A-Za-z0-9_]*)+", action):
            raise ValueError("Action names must be absolute, with no wildcards")
        for suffix in ("send_goal", "get_result", "cancel_goal", "feedback", "status"):
            name = action + "/_action/" + suffix
            data_keys.append(f"{domain}/{name.lstrip('/')}/*/*")
            # zid/nid/eid/kind/enclave/namespace/node, then mangled ROS name,
            # type/hash/qos. Keep node tokens and all other entities untouched.
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
