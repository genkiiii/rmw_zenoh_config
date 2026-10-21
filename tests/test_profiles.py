import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

root = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('merge', root / 'scripts/merge-profiles.py')
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)

class ProfileTests(unittest.TestCase):
    def test_shipped_profiles_empty(self):
        for path in (root / 'profiles').glob('*.json'):
            profile = json.loads(path.read_text())
            self.assertIsNone(merge.acl.build_acl(profile, '35', 'eth0'))

    def test_unknown_and_missing_device_fail(self):
        with self.assertRaises(ValueError):
            merge.merge_profiles(root / 'profiles')
        with self.assertRaises(ValueError):
            merge.merge_profiles(root / 'profiles', device='   ')
        with self.assertRaises(ValueError):
            merge.merge_profiles(root / 'profiles', 'd37pxi', 'zx200')
        with self.assertRaises(OSError):
            merge.merge_profiles(root / 'profiles', 'does_not_exist')
        with self.assertRaises(ValueError):
            merge.merge_profiles(root / 'profiles', '../d37pxi')

    def test_merge_deduplicates_and_handles_all_entity_types(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('one', 'two'):
                Path(directory, name + '.json').write_text(json.dumps({
                    'allow': {}, 'deny': {'topics': ['/robot/state'],
                    'services': ['/robot/reset'], 'actions': ['/robot/nav']}}))
            result = merge.merge_profiles(directory, device='one two')
            self.assertEqual(result, merge.merge_profiles(directory, devices='one two'))
            self.assertEqual(result, merge.merge_profiles(directory, device='  one   two one  '))
            self.assertEqual(result['deny']['actions'], ['/robot/nav'])
            policy = merge.acl.build_acl(result, '35', 'eth0')
            keys = policy['rules'][0]['key_exprs']
            self.assertEqual(len(keys), 7)
            self.assertIn('35/robot/state/*/*', keys)
            self.assertIn('35/robot/reset/*/*', keys)

    def test_nonempty_allow_switches_to_whitelist(self):
        policy = merge.acl.build_acl({'allow': {'topics': ['/robot/state']}}, '35', 'eth0')
        self.assertEqual(policy['default_permission'], 'deny')
        local = next(s for s in policy['subjects'] if s['id'] == 'local')
        self.assertEqual(local['interfaces'], ['lo'])
        rule = next(r for r in policy['rules'] if r['id'] == 'allow-action-data')
        self.assertIn('35/robot/state/*/*', rule['key_exprs'])

    def test_empty_profile_does_not_resolve_interface_or_emit_override(self):
        with patch('sys.argv', ['generate-acl', '--profile', str(root / 'profiles/d37pxi.json'), '--server', '192.168.1.70', '--domain', '35']), \
             patch.object(merge.acl, 'detect_interface') as detect, \
             patch('sys.stdout') as stdout:
            merge.acl.main()
            detect.assert_not_called()
            stdout.write.assert_not_called()

class MixedPolicyTests(unittest.TestCase):
    def test_allow_and_deny_same_name_are_both_generated(self):
        section = {'topics': ['/robot/state'], 'services': [], 'actions': []}
        policy = merge.acl.build_acl({'allow': section, 'deny': section}, '35', 'eth0')
        matching = [r for r in policy['rules']
                    if '35/robot/state/*/*' in r['key_exprs']]
        self.assertEqual({r['permission'] for r in matching}, {'allow', 'deny'})
        self.assertEqual(policy['default_permission'], 'deny')
        central = next(p for p in policy['policies'] if p['subjects'] == ['central-route'])
        self.assertNotIn('allow-local', central['rules'])
        self.assertIn('allow-action-data', central['rules'])
        self.assertIn('deny-action-data', central['rules'])

    def test_allowed_action_includes_services_topics_and_discovery(self):
        policy = merge.acl.build_acl({'allow': {'actions': ['/d37pxi/zenoh/navigate_to_pose']}}, '35', 'eth0')
        data = next(r for r in policy['rules'] if r['id'] == 'allow-action-data')
        graph = next(r for r in policy['rules'] if r['id'] == 'allow-action-discovery')
        self.assertEqual(len(data['key_exprs']), 5)
        self.assertEqual(len(graph['key_exprs']), 5)
        self.assertIn('35/d37pxi/zenoh/navigate_to_pose/_action/get_result/*/*', data['key_exprs'])
        self.assertIn('35/d37pxi/zenoh/navigate_to_pose/_action/feedback/*/*', data['key_exprs'])
        self.assertFalse(any('35/d37pxi/navigate_to_pose/' in k for k in data['key_exprs']))

    def test_profile_union_enables_allow_mode_and_keeps_other_denials(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'a.json').write_text(json.dumps({'allow': {'topics': ['/a/state']}}))
            Path(directory, 'b.json').write_text(json.dumps({'deny': {'services': ['/b/reset']}}))
            profile = merge.merge_profiles(directory, device='a b')
            policy = merge.acl.build_acl(profile, '35', 'eth0')
            self.assertEqual(policy['default_permission'], 'deny')
            self.assertTrue(any('35/b/reset/*/*' in r['key_exprs'] and r['permission'] == 'deny'
                                for r in policy['rules']))
