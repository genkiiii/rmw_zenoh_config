import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('deployment', ROOT / 'scripts/read-deployment.py')
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)

class DeploymentTests(unittest.TestCase):
    def test_validation_rejects_unknown_missing_and_executable_values(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / 'test.env'
            for text in ('ROLE=vehicle\nSERVER=192.168.1.70\n',
                         'ROLE=vehicle\nSERVER=192.168.1.70\nROS_DOMAIN_ID=233\n',
                         'ROLE=vehicle\nSERVER=$(touch sentinel)\nROS_DOMAIN_ID=35\n',
                         'ROLE=vehicle\nSERVER=192.168.1.70\nROS_DOMAIN_ID=35\nRUN_USER=bad\n'):
                env.write_text(text)
                with self.assertRaises(ValueError):
                    deployment.read_deployment(env)
            env.write_text('ROLE=control\nSERVER="192.168.1.71" # comment\nROS_DOMAIN_ID=13\n')
            self.assertEqual(deployment.read_deployment(env)['ROS_DOMAIN_ID'], '13')

    def test_update_env_and_apply_profile_are_independent(self):
        # Run only the actual pre-service portion in an isolated tree; never
        # touch /etc, /usr/local or systemd during the test.
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / 'scripts').mkdir()
            (repo / 'profiles').mkdir()
            (repo / 'config').mkdir()
            installed = repo / 'installed'
            installed.mkdir()
            for name in ('read-deployment.py', 'merge-profiles.py', 'generate-acl.py'):
                shutil.copy(ROOT / 'scripts' / name, repo / 'scripts' / name)
            script = (ROOT / 'scripts/manage.sh').read_text()
            script = script[:script.index('\nesac') + len('\nesac')]
            script = '\n'.join(line for line in script.splitlines() if not line.startswith('[[ $EUID'))
            script = script.replace('config=/etc/zenoh/rmw_zenoh_config', f'config="{installed}"\ngetent() {{ return 0; }}')
            target = repo / 'scripts/manage.sh'
            target.write_text(script)
            runtime = installed / 'deployment.env'
            runtime.write_text('ROLE=vehicle\nRUN_USER=original_user\nSERVER=192.168.1.70\nDOMAIN_ID=35\n')
            profile = installed / 'deny-profile.json'
            profile.write_text('{"deny_actions":["/original/action"]}\n')
            router = installed / 'router.json5'
            router.write_text('original router')
            local = repo / 'config/deployment.env'
            def run(*args):
                return subprocess.run(['bash', str(target), *args], capture_output=True, text=True)
            # No local env: keep old deployment untouched.
            before = runtime.read_text()
            self.assertNotEqual(run('update').returncode, 0)
            self.assertEqual(runtime.read_text(), before)
            local.write_text('ROLE=control\nSERVER=192.168.1.71\nROS_DOMAIN_ID=13\n')
            self.assertEqual(run('update').returncode, 0)
            self.assertIn('RUN_USER=original_user', runtime.read_text())
            self.assertIn('ROS_DOMAIN_ID=13', runtime.read_text())
            self.assertIn('SERVER=192.168.1.71', runtime.read_text())
            self.assertIn('ROLE=control', runtime.read_text())
            self.assertEqual((installed / 'deployment.env.bak').read_text(), before)
            self.assertEqual(profile.read_text(), '{"deny_actions":["/original/action"]}\n')
            self.assertEqual(router.read_text(), 'original router')
            # apply-profile uses installed env and leaves local changes pending.
            applied_env = runtime.read_text()
            local.write_text('ROLE=vehicle\nSERVER=192.168.1.99\nROS_DOMAIN_ID=99\n')
            (repo / 'profiles/test.json').write_text('{"deny":{"topics":["/robot/state"]}}')
            self.assertEqual(run('apply-profile', 'test').returncode, 0)
            self.assertEqual(runtime.read_text(), applied_env)
            self.assertEqual(json.loads(profile.read_text())['deny']['topics'], ['/robot/state'])
            # Invalid local env cannot overwrite a good deployment.
            local.write_text('ROLE=bad\nSERVER=192.168.1.70\nROS_DOMAIN_ID=35\n')
            self.assertNotEqual(run('update').returncode, 0)
            self.assertEqual(runtime.read_text(), applied_env)
