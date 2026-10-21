import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('acl', Path(__file__).parents[1] / 'scripts/generate-acl.py')
acl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acl)

class ACLTests(unittest.TestCase):
    def test_action_boundaries_and_local_scope(self):
        policy = acl.build_acl({'deny_actions': ['/d37pxi/navigate_to_pose']}, '35', 'enp5s0')
        self.assertEqual(policy['default_permission'], 'allow')
        self.assertEqual(policy['subjects'][0]['interfaces'], ['enp5s0'])
        data, graph = policy['rules']
        self.assertEqual(len(data['key_exprs']), 5)
        self.assertEqual(len(graph['key_exprs']), 5)
        self.assertIn('35/d37pxi/navigate_to_pose/_action/send_goal/*/*', data['key_exprs'])
        # Match the actual entity shape from rmw_zenoh 0.1.11.
        token = '@ros2_lv/35/zid/1/2/SS/%/%d37pxi/nav2/%d37pxi%navigate_to_pose%_action%send_goal/type/hash/qos'
        patterns = [x.split('/') for x in graph['key_exprs']]
        chunks = token.split('/')
        self.assertTrue(any(len(p) == len(chunks) and all(a == '*' or a == b for a,b in zip(p,chunks)) for p in patterns))
        for rule in policy['rules']:
            self.assertFalse(any('/zenoh/' in x or '%zenoh%' in x for x in rule['key_exprs']))

    def test_invalid_profile_rejected(self):
        for name in ('d37pxi/foo', '/d37pxi/**', '/d37pxi/foo;bar', '/d37pxi/'):
            with self.assertRaises(ValueError):
                acl.build_acl({'deny_actions': [name]}, '35', 'eth0')

    @patch.object(acl.socket, 'if_nametoindex', return_value=3)
    @patch.object(acl.subprocess, 'run')
    def test_route_is_resolved_on_each_call(self, run, index):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, json.dumps([{'dev':'enp5s0'}])),
            subprocess.CompletedProcess([], 0, '[]'),
            subprocess.CompletedProcess([], 0, json.dumps([{'dev':'wlan0'}])),
            subprocess.CompletedProcess([], 0, '[]')]
        self.assertEqual(acl.detect_interface('192.168.1.70'), 'enp5s0')
        self.assertEqual(acl.detect_interface('192.168.1.70'), 'wlan0')

    @patch.object(acl.subprocess, 'run')
    def test_no_route_or_loopback_fails_closed(self, run):
        for route in ([], [{'dev':'lo'}], [{'type':'unreachable'}]):
            run.return_value = subprocess.CompletedProcess([], 0, json.dumps(route))
            with self.assertRaises(ValueError):
                acl.detect_interface('192.168.1.70')

    @patch.object(acl.subprocess, 'run')
    def test_local_server_rejected(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, '[{"dev":"eth0"}]'),
            subprocess.CompletedProcess([], 0, '[{"addr_info":[{"local":"192.168.1.70"}]}]')]
        with self.assertRaises(ValueError):
            acl.detect_interface('192.168.1.70')
