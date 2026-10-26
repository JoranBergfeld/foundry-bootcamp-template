import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SHELLS = ["bash"] + (["pwsh"] if shutil.which("pwsh") else [])


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.project = self.directory / "project with spaces"
        self.project.mkdir()
        for name in ("provision.sh", "provision.ps1", "main.bicep"):
            if (ROOT / name).exists():
                shutil.copy2(ROOT / name, self.project / name)
        if (ROOT / "labautomation").exists():
            shutil.copytree(ROOT / "labautomation", self.project / "labautomation")
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.log = self.directory / "az.jsonl"
        fake_az = self.bin / "az"
        fake_az.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "with open(os.environ['AZ_LOG'], 'a') as log:\n"
            "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:3] == ['account', 'show']:\n"
            "    if os.environ.get('AZ_FAIL') == 'auth':\n"
            "        print('Please run az login.', file=sys.stderr)\n"
            "        sys.exit(1)\n"
            "elif sys.argv[1:4] == ['deployment', 'sub', 'create']:\n"
            "    if os.environ.get('AZ_FAIL') == 'deploy':\n"
            "        print('Deployment failed.', file=sys.stderr)\n"
            "        sys.exit(1)\n"
            "    print('{}')\n"
            "else:\n"
            "    print('Unexpected Azure CLI command', file=sys.stderr)\n"
            "    sys.exit(2)\n"
        )
        fake_az.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "AZ_LOG": str(self.log),
        }
        self.env.pop("AZ_FAIL", None)

    def run_script(self, shell, *args):
        if shell == "bash":
            command = ["bash", str(self.project / "provision.sh")]
        else:
            command = [
                "pwsh", "-NoLogo", "-NoProfile", "-File",
                str(self.project / "provision.ps1"),
            ]
        return subprocess.run(
            [*command, *args], cwd=self.directory, env=self.env,
            capture_output=True, text=True, timeout=30,
        )

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def suffix(self):
        return (self.project / ".provision" / "suffix").read_text().strip()

    def test_creates_suffix_and_reuses_it_across_shells(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_script(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                suffix = self.suffix()
                self.assertRegex(suffix, r"^[0-9a-f]{8}$")
                result = self.run_script(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.suffix(), suffix)
        deployments = [call for call in self.calls() if call[:3] == [
            "deployment", "sub", "create"
        ]]
        self.assertEqual(len(deployments), 2 * len(SHELLS))
        for call in deployments:
            self.assertEqual(call[call.index("--location") + 1], "westeurope")
            self.assertEqual(
                Path(call[call.index("--template-file") + 1]),
                self.project / "main.bicep",
            )
            self.assertIn(f"suffix={self.suffix()}", call)

    def test_forwards_location_and_subscription_without_changing_defaults(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                args = (
                    ["--location", "swedencentral", "--subscription", "test-sub"]
                    if shell == "bash"
                    else ["-Location", "swedencentral", "-Subscription", "test-sub"]
                )
                result = self.run_script(shell, *args)
                self.assertEqual(result.returncode, 0, result.stderr)
        for call in self.calls():
            self.assertEqual(call[call.index("--subscription") + 1], "test-sub")
            if call[:3] == ["deployment", "sub", "create"]:
                self.assertIn("location=swedencentral", call)
                self.assertEqual(
                    call[call.index("--location") + 1], "swedencentral"
                )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell is not installed")
    def test_powershell_generated_suffix_is_reused_by_bash(self):
        result = self.run_script("pwsh")
        self.assertEqual(result.returncode, 0, result.stderr)
        suffix = self.suffix()
        self.assertRegex(suffix, r"^[0-9a-f]{8}$")
        result = self.run_script("bash")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.suffix(), suffix)

    def test_authentication_failure_stops_before_deployment(self):
        self.env["AZ_FAIL"] = "auth"
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_script(shell)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("az login", result.stderr)
        self.assertTrue(all(call[:2] == ["account", "show"] for call in self.calls()))

    def test_deployment_failure_preserves_suffix_for_retry(self):
        self.env["AZ_FAIL"] = "deploy"
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_script(shell)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Deployment failed", result.stderr)
                suffix = self.suffix()
                self.env.pop("AZ_FAIL")
                result = self.run_script(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.suffix(), suffix)
                self.env["AZ_FAIL"] = "deploy"

    def test_invalid_suffix_is_not_replaced(self):
        state = self.project / ".provision" / "suffix"
        state.parent.mkdir()
        for value in ("", "not-a-suffix", "1234567", "123456789", "AB12CD34"):
            state.write_text(value)
            for shell in SHELLS:
                with self.subTest(shell=shell, value=value):
                    result = self.run_script(shell)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("suffix", result.stderr.lower())
                    self.assertEqual(state.read_text(), value)
        self.assertFalse(any(call[:3] == [
            "deployment", "sub", "create"
        ] for call in self.calls()))

    def test_invalid_arguments_do_not_deploy(self):
        for shell in SHELLS:
            cases = (
                [("--unknown",), ("--location",), ("--location", "")]
                if shell == "bash"
                else [("-Unknown",), ("-Location",), ("-Location", "")]
            )
            for args in cases:
                with self.subTest(shell=shell, args=args):
                    result = self.run_script(shell, *args)
                    self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
