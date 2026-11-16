import csv
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from labautomation import environment as env


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tickets.csv"
        self.row = {field: "example" for field in env.STRING_FIELDS}
        self.row.update(
            ticket_id="TCKT_000001", created_at="2024-01-31T05:14:27",
            resolution_time_hours="", reopened="0", csat_score="0", has_attachment="1",
        )

    def write_rows(self, rows):
        with self.path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=sorted(env.COLUMNS))
            writer.writeheader()
            writer.writerows(rows)

    def test_preserves_text_and_converts_nullable_dates_and_flags(self):
        self.row["initial_message"] = 'Quoted "text", commas\nand newlines'
        self.write_rows([self.row])
        document, = env.read_tickets(self.path)
        self.assertEqual(document["initial_message"], self.row["initial_message"])
        self.assertEqual(document["created_at"], "2024-01-31T05:14:27+00:00")
        self.assertIsNone(document["resolution_time_hours"])
        self.assertEqual(document["csat_score"], 0)
        self.assertFalse(document["reopened"])
        self.assertTrue(document["has_attachment"])
        self.assertEqual(set(document), env.COLUMNS)

    def test_duplicate_keys_and_invalid_values_fail_explicitly(self):
        self.write_rows([self.row, self.row])
        with self.assertRaisesRegex(ValueError, "duplicate ticket_id"):
            list(env.read_tickets(self.path))
        for field, value in (("has_attachment", "yes"), ("created_at", "invalid"),
                             ("resolution_time_hours", "inf"), ("ticket_id", "not a key")):
            with self.subTest(field=field):
                self.write_rows([{**self.row, field: value}])
                with self.assertRaisesRegex(ValueError, "CSV line 2"):
                    list(env.read_tickets(self.path))

    def test_changed_schema_and_incomplete_dataset_fail_before_upload(self):
        self.path.write_text("ticket_id\none\n")
        with self.assertRaisesRegex(ValueError, "Unexpected dataset columns"):
            list(env.read_tickets(self.path))
        self.write_rows([self.row])
        with patch.object(env, "token_for") as token:
            with self.assertRaisesRegex(ValueError, "Expected 100000"):
                env.seed({}, "subscription", self.path)
            token.assert_not_called()

    def test_retries_only_failed_search_documents(self):
        with patch.object(env, "request", side_effect=[
            {"value": [{"key": "one", "status": True},
                       {"key": "two", "status": False, "statusCode": 503}]},
            {"value": [{"key": "two", "status": True}]},
        ]) as request, patch.object(env.time, "sleep"):
            env.upload_batch("https://test", "token", [{"ticket_id": "one"}, {"ticket_id": "two"}])
        retry = request.call_args_list[1].kwargs["body"]["value"]
        self.assertEqual(retry, [{"@search.action": "mergeOrUpload", "ticket_id": "two"}])

    def test_search_item_failure_is_not_reported_as_success(self):
        with patch.object(env, "request", return_value={"value": [
            {"key": "one", "status": False, "statusCode": 400, "errorMessage": "Invalid field"}
        ]}):
            with self.assertRaisesRegex(RuntimeError, "Search rejected documents"):
                env.upload_batch("https://test", "token", [{"ticket_id": "one"}])

    def test_rbac_propagation_retries_but_bad_requests_do_not(self):
        for code, count in ((403, 3), (429, 3), (400, 1)):
            with self.subTest(code=code):
                error = HTTPError("https://test", code, "failure", {}, None)
                with patch.object(env, "urlopen", side_effect=error) as urlopen, \
                     patch.object(env.time, "sleep"):
                    with self.assertRaisesRegex(RuntimeError, f"HTTP {code}"):
                        env.request("https://test", attempts=3)
                self.assertEqual(urlopen.call_count, count)

    def test_storage_network_denial_does_not_wait_for_rbac_propagation(self):
        error = HTTPError("https://test", 403, "denied", {},
                          io.BytesIO(b"<Error><Code>AuthorizationFailure</Code></Error>"))
        with patch.object(env, "urlopen", side_effect=error) as urlopen, \
             patch.object(env.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "Storage network access is blocked"):
                env.request("https://test")
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()


class CapacityFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(env, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def run_provision(self, results, stuck=(), existing=()):
        """Fake az keyed by region; results map region -> outputs, exception, or callable."""
        groups = set(existing)

        def fake_az(*arguments, **kwargs):
            if arguments[:2] == ("account", "show"):
                return {"id": "sub"}
            if arguments[:2] == ("provider", "list"):
                return [{"namespace": namespace, "registrationState": "Registered"}
                        for namespace in env.PROVIDERS]
            if arguments[:2] == ("group", "exists"):
                return arguments[arguments.index("--name") + 1] in groups
            if arguments[:3] == ("deployment", "sub", "create"):
                location = next(arg for arg in arguments if str(arg).startswith("location="))[9:]
                groups.add(f"rg-foundry-bootcamp-12345678-{location}")
                result = results[location]
                result = result() if callable(result) else result
                if isinstance(result, Exception):
                    raise result
                return result
            if arguments[1:3] == ("sub", "cancel") or arguments[1:3] == ("group", "cancel"):
                return None
            if arguments[:2] == ("group", "delete"):
                name = arguments[arguments.index("--name") + 1]
                if name not in stuck:
                    groups.discard(name)
                return None
            if arguments[:3] == ("cognitiveservices", "account", "list-deleted"):
                return [{"id": "/subscriptions/sub/providers/Microsoft.CognitiveServices/locations/"
                               "westeurope/resourceGroups/rg-foundry-bootcamp-12345678-westeurope/"
                               "deletedAccounts/aif-x", "name": "aif-x", "location": "westeurope"}]
            if arguments[:3] == ("cognitiveservices", "account", "purge"):
                return None
            raise AssertionError(arguments)

        return patch.object(env, "az", side_effect=fake_az)

    @staticmethod
    def commands(az, *prefix):
        return [call.args for call in az.call_args_list if call.args[:len(prefix)] == prefix]

    def test_races_regions_in_parallel_and_keeps_only_the_first_success(self):
        winner_done = threading.Event()

        def winner():
            winner_done.set()
            return {"searchEndpoint": {"value": "https://winner"}}

        def slow_success():
            winner_done.wait(5)
            time.sleep(0.2)
            return {"searchEndpoint": {"value": "https://late"}}

        results = {"westeurope": env.AzureError("(SkuNotAvailable) capacity"),
                   "swedencentral": winner, "francecentral": slow_success}
        with self.run_provision(results) as az, patch.object(env, "seed") as seed:
            env.provision("12345678", list(env.REGIONS), "sub", ["user"])
        self.assertEqual(len(self.commands(az, "deployment", "sub", "create")), 3)
        deleted = {args[args.index("--name") + 1] for args in self.commands(az, "group", "delete")}
        self.assertEqual(deleted, {"rg-foundry-bootcamp-12345678-westeurope",
                                   "rg-foundry-bootcamp-12345678-francecentral"})
        self.assertTrue(self.commands(az, "deployment", "sub", "cancel"))
        self.assertEqual(len(self.commands(az, "cognitiveservices", "account", "purge")), 1)
        state = json.loads((self.root / ".provision/sub-12345678.json").read_text())
        self.assertEqual(state["location"], "swedencentral")
        seed.assert_called_once_with({"searchEndpoint": "https://winner"}, "sub", None)

        with self.run_provision({"swedencentral": {}},
                                existing={"rg-foundry-bootcamp-12345678-swedencentral"}) as az, \
             patch.object(env, "seed"):
            env.provision("12345678", ["westeurope"], "sub", [])
        (deployment,) = self.commands(az, "deployment", "sub", "create")
        self.assertIn("location=swedencentral", deployment)
        self.assertFalse(self.commands(az, "group", "delete"))

    def test_non_retryable_failures_are_raised_after_cleaning_up_this_race(self):
        results = {"westeurope": env.AzureError("AuthorizationFailed"),
                   "swedencentral": env.AzureError("SkuNotAvailable"),
                   "francecentral": env.AzureError("InvalidTemplate")}
        with self.run_provision(results) as az, patch.object(env, "seed") as seed:
            with self.assertRaisesRegex(env.AzureError, "AuthorizationFailed|InvalidTemplate"):
                env.provision("12345678", list(env.REGIONS), "sub", [])
        self.assertEqual(len(self.commands(az, "group", "delete")), 3)
        seed.assert_not_called()

    def test_nested_sku_capacity_and_mixed_fatal_errors(self):
        error = {"error": {"code": "DeploymentFailed", "details": [
            {"code": "ResourcesForSkuUnavailable", "message": "Try another region"}
        ]}}
        self.assertTrue(env.capacity_failure("ERROR: " + json.dumps(error)))
        error["error"]["details"].append({"code": "ValidationError", "message": "Bad metadata"})
        self.assertFalse(env.capacity_failure("ERROR: " + json.dumps(error)))

    def test_untracked_existing_groups_are_never_deployed_into_or_deleted(self):
        with self.run_provision({}, existing={"rg-foundry-bootcamp-12345678-swedencentral"}) as az:
            with self.assertRaisesRegex(RuntimeError, "Untracked lab groups"):
                env.provision("12345678", list(env.REGIONS), "sub", [])
        self.assertFalse(self.commands(az, "deployment", "sub", "create"))
        self.assertFalse(self.commands(az, "group", "delete"))

    def test_cleanup_failure_is_reported(self):
        results = {"westeurope": env.AzureError("QuotaExceeded"), "swedencentral": {},
                   "francecentral": env.AzureError("QuotaExceeded")}
        with self.run_provision(results, stuck={"rg-foundry-bootcamp-12345678-westeurope"}), \
             patch.object(env, "seed"):
            with self.assertRaisesRegex(RuntimeError, "Cleanup incomplete"):
                env.provision("12345678", list(env.REGIONS), "sub", [])

    def test_failed_seed_preserves_successful_infrastructure_for_retry(self):
        results = {location: env.AzureError("QuotaExceeded") for location in env.REGIONS}
        results["francecentral"] = {}
        with self.run_provision(results), \
             patch.object(env, "seed", side_effect=RuntimeError("ingestion failed")):
            with self.assertRaisesRegex(RuntimeError, "ingestion failed"):
                env.provision("12345678", list(env.REGIONS), "sub", [])
        self.assertTrue((self.root / ".provision/sub-12345678.json").exists())
    def test_upgrades_legacy_group_in_place_without_creating_a_second_lab(self):
        def fake_az(*arguments, **kwargs):
            if arguments[:2] == ("account", "show"):
                return {"id": "sub"}
            if arguments[:2] == ("provider", "list"):
                return [{"namespace": namespace, "registrationState": "Registered"}
                        for namespace in env.PROVIDERS]
            if arguments[:2] == ("group", "exists"):
                return True
            if arguments[:2] == ("group", "show"):
                return {"name": "rg-foundry-bootcamp-12345678", "location": "swedencentral"}
            if arguments[:3] == ("deployment", "sub", "create"):
                self.assertIn("resourceGroupName=rg-foundry-bootcamp-12345678", arguments)
                self.assertIn("location=swedencentral", arguments)
                return {}
            raise AssertionError(arguments)

        with patch.object(env, "az", side_effect=fake_az), patch.object(env, "seed"):
            env.provision("12345678", list(env.REGIONS), "sub", [])

    def test_all_regions_exhausted_does_not_report_success(self):
        results = {location: env.AzureError("SkuNotAvailable") for location in env.REGIONS}
        with self.run_provision(results), \
             patch.object(env, "seed") as seed:
            with self.assertRaisesRegex(RuntimeError, "Capacity exhausted"):
                env.provision("12345678", list(env.REGIONS), "sub", [])
        seed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
