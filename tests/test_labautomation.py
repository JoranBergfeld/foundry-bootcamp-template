import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell is not installed")
class LabAutomationTests(unittest.TestCase):
    def run_hook(self, hook="deploy-lab.ps1", failure="", **overrides):
        parameters = {
            "SubscriptionId": "test-sub",
            "PreferredLocation": ["westeurope", "swedencentral"],
            "AllowedEntraUserIds": ["participant-1", "participant-2"],
        }
        if hook == "deploy-lab.ps1":
            parameters.update(
                DeploymentType="resourcegroup", ResourceGroupName="participant-rg"
            )
        parameters.update(overrides)
        command = r"""
$ErrorActionPreference = 'Stop'
$global:calls = [System.Collections.Generic.List[object]]::new()
function Get-AzContext {
    @{ Subscription = @{ Id = 'test-sub' } }
}
function Get-MhhStableHash {
    param([string[]]$Values, [int]$Length)
    $global:calls.Add(@{ kind = 'hash'; values = $Values; length = $Length })
    '0123456789ab'
}
function Invoke-MhhDeploymentWithRegionFallback {
    param($PreferredLocations, $ResourceGroupName, $RgOwnerEntraObjectIds,
          $TemplateFile, $TemplateParameterObject, $DeploymentNamePrefix)
    $global:calls.Add(@{
        kind = 'deploy'; regions = $PreferredLocations
        group = $ResourceGroupName; owners = $RgOwnerEntraObjectIds
        template = $TemplateFile; parameters = $TemplateParameterObject
    })
    if ($env:HOOK_FAILURE -eq 'deploy') { throw 'Deployment failed' }
    @{
        Success = $true
        LocationUsed = 'swedencentral'
        Outputs = @{
            foundryAccountName = 'aif-test'
            foundryProjectName = 'bootcamp'
            foundryProjectEndpoint = 'https://aif-test.services.ai.azure.com/api/projects/bootcamp'
        }
    }
}
function Get-AzResourceProvider {
    param($ProviderNamespace)
    $global:calls.Add(@{ kind = 'get-provider'; provider = $ProviderNamespace })
    @{ RegistrationState = $(if ($env:HOOK_FAILURE -in @('unregistered', 'register')) {
        'NotRegistered'
    } else { 'Registered' }) }
}
function Register-AzResourceProvider {
    param($ProviderNamespace)
    $global:calls.Add(@{ kind = 'register-provider'; provider = $ProviderNamespace })
    if ($env:HOOK_FAILURE -eq 'register') { throw 'Registration failed' }
}
try {
    $parameters = $env:HOOK_PARAMETERS | ConvertFrom-Json -AsHashtable
    $credentials = @(& (Join-Path $env:HOOK_ROOT "labautomation/$env:HOOK_NAME") @parameters)
    @{ calls = @($global:calls); credentials = $credentials } |
        ConvertTo-Json -Depth 10 -Compress
} catch {
    @{ calls = @($global:calls); error = $_.Exception.Message } |
        ConvertTo-Json -Depth 10 -Compress
    exit 1
}
"""
        result = subprocess.run(
            ["pwsh", "-NoLogo", "-NoProfile", "-Command", command],
            env={
                **os.environ,
                "HOOK_ROOT": str(ROOT),
                "HOOK_NAME": hook,
                "HOOK_PARAMETERS": json.dumps(parameters),
                "HOOK_FAILURE": failure,
            },
            capture_output=True, text=True, timeout=30,
        )
        return result, json.loads(result.stdout.strip().splitlines()[-1])

    def test_resource_group_scopes_use_platform_group_and_actual_outputs(self):
        for scope in ("resourcegroup", "resourcegroup-with-subscriptionowner"):
            with self.subTest(scope=scope):
                result, data = self.run_hook(DeploymentType=scope)
                self.assertEqual(result.returncode, 0, data)
                deployments = [c for c in data["calls"] if c["kind"] == "deploy"]
                self.assertEqual(len(deployments), 1)
                deployment = deployments[0]
                self.assertEqual(deployment["group"], "participant-rg")
                self.assertEqual(deployment["owners"], ["participant-1", "participant-2"])
                self.assertEqual(deployment["regions"], ["westeurope", "swedencentral"])
                self.assertEqual(
                    Path(deployment["template"]), ROOT / "labautomation/main.bicep"
                )
                self.assertNotIn("location", deployment["parameters"])
                credentials = {
                    c["HackboxCredential"]["name"]: c["HackboxCredential"]["value"]
                    for c in data["credentials"]
                }
                self.assertEqual(credentials, {
                    "ResourceGroupName": "participant-rg",
                    "EffectiveLocation": "swedencentral",
                    "FoundryAccountName": "aif-test",
                    "FoundryProjectName": "bootcamp",
                    "FoundryProjectEndpoint":
                        "https://aif-test.services.ai.azure.com/api/projects/bootcamp",
                })

    def test_subscription_scope_derives_stable_participant_group(self):
        result, data = self.run_hook(
            DeploymentType="subscription", ResourceGroupName=""
        )
        self.assertEqual(result.returncode, 0, data)
        hash_call = next(c for c in data["calls"] if c["kind"] == "hash")
        self.assertEqual(hash_call["values"], ["participant-1", "participant-2"])
        deployment = next(c for c in data["calls"] if c["kind"] == "deploy")
        self.assertEqual(deployment["group"], "rg-foundry-bootcamp-0123456789ab")

    def test_invalid_inputs_stop_before_deployment(self):
        cases = [
            ({"ResourceGroupName": ""}, "ResourceGroupName is required"),
            ({"DeploymentType": "resourcegroup-with-subscriptionowner",
              "ResourceGroupName": " "}, "ResourceGroupName is required"),
            ({"AllowedEntraUserIds": []}, "AllowedEntraUserIds"),
            ({"AllowedEntraUserIds": [""]}, "AllowedEntraUserIds"),
            ({"SubscriptionId": "wrong-sub"}, "active Azure context"),
            ({"DeploymentType": "invalid"}, "ValidateSet"),
        ]
        for overrides, error in cases:
            with self.subTest(overrides=overrides):
                result, data = self.run_hook(**overrides)
                self.assertNotEqual(result.returncode, 0, data)
                self.assertIn(error, data["error"])
                self.assertFalse(any(c["kind"] == "deploy" for c in data["calls"]))

    def test_default_region_is_used_when_no_preference_is_supplied(self):
        result, data = self.run_hook(PreferredLocation=[])
        self.assertEqual(result.returncode, 0, data)
        deployment = next(c for c in data["calls"] if c["kind"] == "deploy")
        self.assertEqual(deployment["regions"], ["westeurope"])

    def test_failed_deployment_does_not_publish_credentials(self):
        result, data = self.run_hook(failure="deploy")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Deployment failed", data["error"])
        self.assertNotIn("credentials", data)

    def test_shared_hook_registers_only_foundry_provider(self):
        result, data = self.run_hook(
            hook="shared-deploy-lab.ps1", failure="unregistered"
        )
        self.assertEqual(result.returncode, 0, data)
        registrations = [c for c in data["calls"] if c["kind"] == "register-provider"]
        self.assertEqual(registrations, [
            {"kind": "register-provider", "provider": "Microsoft.CognitiveServices"}
        ])
        self.assertEqual(data["credentials"], [])

    def test_shared_hook_skips_registered_provider(self):
        result, data = self.run_hook(hook="shared-deploy-lab.ps1")
        self.assertEqual(result.returncode, 0, data)
        self.assertFalse(any(c["kind"] == "register-provider" for c in data["calls"]))

    def test_shared_hook_rejects_wrong_subscription(self):
        result, data = self.run_hook(
            hook="shared-deploy-lab.ps1", SubscriptionId="wrong-sub"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("active Azure context", data["error"])
        self.assertEqual(data["calls"], [])

    def test_shared_hook_registration_failure_stops_deployment(self):
        result, data = self.run_hook(
            hook="shared-deploy-lab.ps1", failure="register"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Registration failed", data["error"])
        self.assertNotIn("credentials", data)


@unittest.skipUnless(shutil.which("bicep"), "Bicep CLI is not installed")
class FoundryTemplateTests(unittest.TestCase):
    def compile(self, path):
        result = subprocess.run(
            ["bicep", "build", str(ROOT / path), "--stdout"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_foundry_resources(self, template):
        resources = {r["type"]: r for r in template["resources"]}
        self.assertEqual(set(resources), {
            "Microsoft.CognitiveServices/accounts",
            "Microsoft.CognitiveServices/accounts/projects",
        })
        account = resources["Microsoft.CognitiveServices/accounts"]
        self.assertEqual(account["kind"], "AIServices")
        self.assertEqual(account["sku"]["name"], "S0")
        self.assertTrue(account["properties"]["allowProjectManagement"])
        self.assertTrue(account["properties"]["disableLocalAuth"])
        self.assertIn("customSubDomainName", account["properties"])
        self.assertEqual(set(template["outputs"]), {
            "foundryAccountName", "foundryProjectName", "foundryProjectEndpoint"
        })

    def test_lab_template_deploys_only_account_and_project(self):
        template = self.compile("labautomation/main.bicep")
        self.assert_foundry_resources(template)
        self.assertEqual(
            template["parameters"]["location"]["defaultValue"],
            "[resourceGroup().location]",
        )

    def test_root_template_reuses_foundry_template(self):
        template = self.compile("main.bicep")
        resources = {r["type"]: r for r in template["resources"]}
        self.assertEqual(set(resources), {
            "Microsoft.Resources/resourceGroups", "Microsoft.Resources/deployments"
        })
        module = resources["Microsoft.Resources/deployments"]
        self.assert_foundry_resources(module["properties"]["template"])
        self.assertEqual(
            module["properties"]["parameters"]["location"]["value"],
            "[parameters('location')]",
        )
        for name in ("foundryAccountName", "foundryProjectName", "foundryProjectEndpoint"):
            self.assertIn(name, template["outputs"])


if __name__ == "__main__":
    unittest.main()
