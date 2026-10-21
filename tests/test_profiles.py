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
            result = merge.merge_profiles(directory, devices='one two')
            self.assertEqual(result['deny']['actions'], ['/robot/nav'])
            policy = merge.acl.build_acl(result, '35', 'eth0')
            keys = policy['rules'][0]['key_exprs']
            self.assertEqual(len(keys), 7)
            self.assertIn('35/robot/state/*/*', keys)
            self.assertIn('35/robot/reset/*/*', keys)

    def test_nonempty_allow_never_silently_ignored(self):
        with self.assertRaisesRegex(ValueError, 'reserved'):
            merge.acl.normalize_profile({'allow': {'topics': ['/robot/state']}})

    def test_empty_profile_does_not_resolve_interface_or_emit_override(self):
        with patch('sys.argv', ['generate-acl', '--profile', str(root / 'profiles/d37pxi.json'), '--server', '192.168.1.70', '--domain', '35']), \
             patch.object(merge.acl, 'detect_interface') as detect, \
             patch('sys.stdout') as stdout:
            merge.acl.main()
            detect.assert_not_called()
            stdout.write.assert_not_called()
