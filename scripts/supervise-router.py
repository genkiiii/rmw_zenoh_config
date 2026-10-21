#!/usr/bin/env python3
"""Check central reachability at startup and watch ACL interface changes."""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time


def route_interface(server):
    result = subprocess.run(["ip", "-j", "-4", "route", "get", server],
                            check=True, capture_output=True, text=True, timeout=5)
    routes = json.loads(result.stdout)
    if len(routes) == 1 and routes[0].get("type") not in ("unreachable", "blackhole", "prohibit"):
        return routes[0].get("dev")
    return None


def check_central(server, expected_interface=None):
    if expected_interface and route_interface(server) != expected_interface:
        raise OSError("Route interface changed; ACL must be regenerated")
    with socket.create_connection((server, 7447), timeout=3):
        pass


def stop_child(child):
    if child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGINT)
        child.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
    except ProcessLookupError:
        child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("Router command is required")
    expected_interface = None
    override = os.environ.get("ZENOH_CONFIG_OVERRIDE", "")
    if ";access_control=" in override:
        acl = json.loads(override.split(";access_control=", 1)[1])
        expected_interface = acl["subjects"][0]["interfaces"][0]
    # A failed initial probe exits before starting any router process.
    try:
        check_central(args.server, expected_interface)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Central unavailable; router not started: {error}", file=sys.stderr)
        return 1
    child = subprocess.Popen(command, start_new_session=True)
    stopping = False

    def handle_stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)
    next_probe = time.monotonic() + 10
    try:
        while child.poll() is None:
            if stopping:
                return 0
            if expected_interface and time.monotonic() >= next_probe:
                try:
                    current_interface = route_interface(args.server)
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    # A temporarily absent route is not a reason to stop local ROS.
                    print(f"ACL route check unavailable; keeping router running: {error}", file=sys.stderr)
                else:
                    if current_interface and current_interface != expected_interface:
                        print("ACL interface changed; restarting router to regenerate ACL", file=sys.stderr)
                        return 1
                next_probe = time.monotonic() + 10
            time.sleep(0.2)
        return child.returncode if child.returncode >= 0 else 1
    finally:
        stop_child(child)


if __name__ == "__main__":
    sys.exit(main())
