import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('supervisor', Path(__file__).parents[1] / 'scripts/supervise-router.py')
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)

class SupervisorTests(unittest.TestCase):
    def test_unavailable_central_never_starts_router(self):
        with patch.object(sys, 'argv', ['supervisor', '--server', '192.168.1.70', '--', 'router']), \
             patch.dict(supervisor.os.environ, {'ZENOH_CONFIG_OVERRIDE': ''}), \
             patch.object(supervisor, 'check_central', side_effect=OSError('timeout')), \
             patch.object(supervisor.subprocess, 'Popen') as start:
            self.assertEqual(supervisor.main(), 1)
            start.assert_not_called()

    def run_watcher(self, route_results):
        child = MagicMock(pid=12345)
        child.poll.side_effect = [None] * len(route_results) + [0, 0]
        child.returncode = 0
        ticks = iter(range(0, 1000, 11))
        override = 'mode="router";access_control={"subjects":[{"interfaces":["enp5s0"]}]}'
        with patch.object(sys, 'argv', ['supervisor', '--server', '192.168.1.70', '--', 'router']), \
             patch.dict(supervisor.os.environ, {'ZENOH_CONFIG_OVERRIDE': override}), \
             patch.object(supervisor, 'check_central') as probe, \
             patch.object(supervisor, 'route_interface', side_effect=route_results), \
             patch.object(supervisor.subprocess, 'Popen', return_value=child), \
             patch.object(supervisor.signal, 'signal'), \
             patch.object(supervisor.time, 'monotonic', side_effect=lambda: next(ticks)), \
             patch.object(supervisor.time, 'sleep'):
            result = supervisor.main()
            probe.assert_called_once_with('192.168.1.70', 'enp5s0')
            return result

    def test_missing_routes_do_not_stop_router(self):
        self.assertEqual(self.run_watcher([OSError('no route')] * 4), 0)

    def test_unchanged_interface_does_not_trigger_tcp_probe(self):
        self.assertEqual(self.run_watcher(['enp5s0'] * 4), 0)

    def test_changed_interface_requests_restart(self):
        self.assertEqual(self.run_watcher(['wlan0']), 1)

    def test_changed_interface_rejected_before_tcp_probe(self):
        route = subprocess.CompletedProcess([], 0, '[{"dev":"wlan0"}]')
        with patch.object(supervisor.subprocess, 'run', return_value=route), \
             patch.object(supervisor.socket, 'create_connection') as connect:
            with self.assertRaisesRegex(OSError, 'Route interface changed'):
                supervisor.check_central('192.168.1.70', 'enp5s0')
            connect.assert_not_called()
