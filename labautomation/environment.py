"""Provision the lab and load the pinned Kaggle dataset using Entra authentication."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
from email.utils import formatdate
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DATASET = "ahsanneural/synthetic-it-support-tickets"
DATASET_URL = f"https://www.kaggle.com/datasets/{DATASET}"
DOWNLOAD_URL = f"https://www.kaggle.com/api/v1/datasets/download/{DATASET}?datasetVersionNumber=1"
CSV_NAME = "synthetic_it_support_tickets.csv"
INDEX_NAME = "it-support-tickets"
REGIONS = ("westeurope", "swedencentral", "francecentral")
RACE_WIDTH = 3
PROVIDERS = {
    "Microsoft.CognitiveServices", "Microsoft.Search", "Microsoft.Storage",
    "Microsoft.Insights", "Microsoft.OperationalInsights",
}
CAPACITY_CODES = {
    "SkuNotAvailable", "InsufficientCapacity", "CapacityUnavailable",
    "InsufficientQuota", "QuotaExceeded", "SpecialFeatureOrQuotaIdRequired",
    "LocationNotAvailableForResourceType", "ResourceProviderUnavailable",
    "RegionDoesNotAllowProvisioning", "ResourcesForSkuUnavailable",
}
STRING_FIELDS = (
    "ticket_id", "customer_id", "customer_segment", "channel", "product_area",
    "issue_type", "priority", "status", "sla_plan", "initial_message",
    "agent_first_reply", "resolution_summary", "customer_sentiment", "platform", "region",
)
TEXT_FIELDS = {"initial_message", "agent_first_reply", "resolution_summary"}
COLUMNS = {*STRING_FIELDS, "created_at", "resolution_time_hours", "reopened",
           "csat_score", "has_attachment"}


class AzureError(RuntimeError):
    pass


def az(*arguments, subscription=None):
    command = [shutil.which("az") or "az", *map(str, arguments)]
    if subscription:
        command += ["--subscription", subscription]
    result = subprocess.run(command + ["--output", "json", "--only-show-errors"],
                            capture_output=True, text=True)
    if result.returncode:
        raise AzureError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def capacity_failure(message):
    if "{" in message:
        try:
            error = json.loads(message[message.index("{"):])
        except ValueError:
            return False

        def leaf_codes(value):
            codes = []
            if isinstance(value, dict):
                children = value.get("details") or []
                if value.get("code") and not children:
                    codes.append(value["code"])
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        codes.extend(leaf_codes(child))
            elif isinstance(value, list):
                for child in value:
                    codes.extend(leaf_codes(child))
            return codes

        codes = set(leaf_codes(error))
        return bool(codes) and codes <= CAPACITY_CODES
    return bool(set(re.findall(r"[A-Za-z][A-Za-z0-9]+", message)) & CAPACITY_CODES)


def request(url, *, method="GET", token=None, body=None, headers=None, attempts=21):
    request_headers = {"User-Agent": "foundry-bootcamp-template/1.0", **(headers or {})}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    if isinstance(body, (dict, list)):
        body = json.dumps(body, allow_nan=False).encode()
        request_headers["Content-Type"] = "application/json"
    for attempt in range(attempts):
        try:
            with urlopen(Request(url, data=body, headers=request_headers, method=method),
                         timeout=120) as response:
                data = response.read()
                if "json" in response.headers.get("Content-Type", ""):
                    return json.loads(data) if data else None
                return data
        except HTTPError as error:
            detail = error.read().decode(errors="replace")[:2000]
            if error.code == 403 and "<Code>AuthorizationFailure</Code>" in detail:
                raise RuntimeError(
                    f"{method} {url}: Storage network access is blocked. Check public network access, "
                    "firewall rules and private endpoint connectivity; RBAC retries cannot fix this."
                ) from error
            if error.code not in {403, 408, 429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise RuntimeError(f"{method} {url}: HTTP {error.code}: {detail}") from error
            delay = min(30, 2 ** attempt)
            print(f"HTTP {error.code} for {method} {url}; retrying in {delay}s "
                  "(RBAC propagation or transient service error).",
                  file=sys.stderr, flush=True)
            time.sleep(delay)


def token_for(resource, subscription):
    return az("account", "get-access-token", "--resource", resource,
              subscription=subscription)["accessToken"]


def read_tickets(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if len(reader.fieldnames or []) != len(COLUMNS) or set(reader.fieldnames or []) != COLUMNS:
            raise ValueError(f"Unexpected dataset columns: {reader.fieldnames}")
        seen = set()
        for line, row in enumerate(reader, 2):
            try:
                key = row["ticket_id"]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", key) or key in seen:
                    raise ValueError("Invalid or duplicate ticket_id")
                seen.add(key)
                document = {name: row[name] for name in STRING_FIELDS}
                created = datetime.fromisoformat(row["created_at"])
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                document["created_at"] = created.isoformat()
                hours = row["resolution_time_hours"]
                document["resolution_time_hours"] = (
                    None if hours.lower() in {"", "nan"} else float(hours)
                )
                document["csat_score"] = int(row["csat_score"])
                for field in ("reopened", "has_attachment"):
                    if row[field] not in {"0", "1"}:
                        raise ValueError(f"Invalid {field}")
                    document[field] = row[field] == "1"
                # Reject non-finite numeric values before sending any batch.
                json.dumps(document, allow_nan=False)
                yield document
            except (ValueError, TypeError) as error:
                raise ValueError(f"Invalid ticket at CSV line {line}: {error}") from error


def index_schema():
    fields = [{
        "name": name, "type": "Edm.String", "key": name == "ticket_id",
        "searchable": name in TEXT_FIELDS,
        "filterable": name not in TEXT_FIELDS,
        "facetable": name not in TEXT_FIELDS and name not in {"ticket_id", "customer_id"},
    } for name in STRING_FIELDS]
    fields += [
        {"name": name, "type": kind, "filterable": True, "sortable": True}
        for name, kind in (
            ("created_at", "Edm.DateTimeOffset"), ("resolution_time_hours", "Edm.Double"),
            ("csat_score", "Edm.Int32"), ("reopened", "Edm.Boolean"),
            ("has_attachment", "Edm.Boolean"),
        )
    ]
    return {"name": INDEX_NAME, "fields": fields}


def upload_batch(endpoint, token, documents):
    pending = documents
    for attempt in range(6):
        result = request(
            f"{endpoint}/indexes/{INDEX_NAME}/docs/index?api-version=2024-07-01",
            method="POST", token=token,
            body={"value": [{"@search.action": "mergeOrUpload", **doc} for doc in pending]},
        )
        entries = result["value"]
        if len(entries) != len(pending):
            raise RuntimeError("Search returned an incomplete indexing response.")
        failed = [entry for entry in entries if not entry["status"]]
        if not failed:
            return
        if attempt == 5 or any(entry["statusCode"] not in {409, 422, 429, 500, 503}
                               for entry in failed):
            raise RuntimeError(f"Search rejected documents: {failed[:3]}")
        print(f"Retrying {len(failed)} rejected Search documents.", file=sys.stderr)
        failed_keys = {entry["key"] for entry in failed}
        pending = [document for document in pending if document["ticket_id"] in failed_keys]
        time.sleep(min(30, 2 ** attempt))


def seed(outputs, subscription, dataset_csv=None):
    with tempfile.TemporaryDirectory(prefix="bootcamp-dataset-") as directory:
        if dataset_csv:
            path = Path(dataset_csv)
        else:
            archive = Path(directory) / "dataset.zip"
            print("Downloading IT Support Tickets, Kaggle version 1.", file=sys.stderr, flush=True)
            archive.write_bytes(request(DOWNLOAD_URL, attempts=1))
            if not zipfile.is_zipfile(archive):
                raise RuntimeError("Kaggle did not return a ZIP. Download version 1 manually and use --dataset-csv.")
            path = Path(directory) / CSV_NAME
            with zipfile.ZipFile(archive) as zipped:
                matches = [name for name in zipped.namelist() if Path(name).name == CSV_NAME]
                if len(matches) != 1:
                    raise ValueError(f"Expected exactly one {CSV_NAME} in Kaggle download.")
                # Copy only the expected member; never extract archive paths.
                with zipped.open(matches[0]) as source, path.open("wb") as target:
                    shutil.copyfileobj(source, target)
        documents = list(read_tickets(path))
        if len(documents) != 100_000:
            raise ValueError(f"Expected 100000 tickets in version 1; received {len(documents)}.")
        raw = path.read_bytes()
        manifest = {
            "dataset": DATASET, "source": DATASET_URL, "version": 1,
            "creator": "Muhammad Ahsan (ahsanneural)",
            "license": "CC BY 4.0", "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
            "rows": len(documents), "columns": 20,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "changes": "Source CSV unchanged; Search converts dates, nullable numbers and booleans.",
        }
        storage_token = token_for("https://storage.azure.com/", subscription)
        blob_root = outputs["storageBlobEndpoint"].rstrip("/") + "/" + outputs["datasetContainerName"]
        for name, body, content_type in (
            (CSV_NAME, raw, "text/csv"),
            ("attribution.json", json.dumps(manifest, indent=2).encode(), "application/json"),
        ):
            request(f"{blob_root}/{name}", method="PUT", token=storage_token, body=body,
                    headers={"x-ms-version": "2023-11-03", "x-ms-blob-type": "BlockBlob",
                             "x-ms-date": formatdate(usegmt=True),
                             "Content-Type": content_type})
        search_token = token_for("https://search.azure.com", subscription)
        endpoint = outputs["searchEndpoint"].rstrip("/")
        request(f"{endpoint}/indexes/{INDEX_NAME}?api-version=2024-07-01",
                method="PUT", token=search_token, body=index_schema())
        for offset in range(0, len(documents), 1000):
            upload_batch(endpoint, search_token, documents[offset:offset + 1000])
            if offset % 10_000 == 0:
                print(f"Indexed {min(offset + 1000, len(documents))}/{len(documents)} tickets.",
                      file=sys.stderr, flush=True)
        for attempt in range(31):
            count = request(f"{endpoint}/indexes/{INDEX_NAME}/docs/$count?api-version=2024-07-01",
                            token=search_token)
            if int(count) == len(documents):
                break
            if attempt == 30:
                raise RuntimeError(f"Search has {count} documents; expected {len(documents)}.")
            time.sleep(10)
        # A count alone doesn't prove retrieval works.
        result = request(f"{endpoint}/indexes/{INDEX_NAME}/docs/search?api-version=2024-07-01",
                         method="POST", token=search_token, body={"search": "*", "top": 1})
        if not result["value"]:
            raise RuntimeError("Search verification returned no tickets.")
        print(f"Verified {len(documents)} searchable tickets and uploaded source CSV + attribution.",
              file=sys.stderr, flush=True)
        return manifest


def deployment_name(suffix, location):
    return f"bootcamp-{suffix}-{location}"


def deploy(suffix, location, group, subscription, principal_ids):
    parameters = [f"location={location}", f"suffix={suffix}", f"resourceGroupName={group}"]
    if principal_ids:
        parameters.append("principalIds=" + json.dumps(principal_ids))
    return az(
        "deployment", "sub", "create", "--name", deployment_name(suffix, location),
        "--location", location, "--template-file", ROOT / "main.bicep",
        "--parameters", *parameters, "--query", "properties.outputs",
        subscription=subscription,
    )


def cancel(suffix, location, group, subscription):
    for arguments in (("deployment", "sub", "cancel", "--name", deployment_name(suffix, location)),
                      ("deployment", "group", "cancel", "--resource-group", group,
                       "--name", "foundry-bootcamp")):
        try:
            az(*arguments, subscription=subscription)
        except AzureError:
            pass  # Already finished or not yet started; the group deletion still follows.


def remove_group(group, subscription):
    if az("group", "exists", "--name", group, subscription=subscription):
        print(f"Deleting extra lab {group}.", file=sys.stderr, flush=True)
        az("group", "delete", "--name", group, "--yes", subscription=subscription)
        if az("group", "exists", "--name", group, subscription=subscription):
            raise RuntimeError(f"Cleanup incomplete for {group}; delete it manually.")
    # Purge soft-deleted Foundry accounts so they hold no quota or block a later retry.
    marker = f"/resourcegroups/{group}/".casefold()
    for account in az("cognitiveservices", "account", "list-deleted", subscription=subscription) or []:
        if marker in account["id"].casefold():
            az("cognitiveservices", "account", "purge", "--name", account["name"],
               "--resource-group", group, "--location", account["location"],
               subscription=subscription)


def provision(suffix, locations, subscription, principal_ids, dataset_csv=None):
    subscription = az("account", "show", subscription=subscription)["id"]
    registered = {provider["namespace"].casefold() for provider in az("provider", "list", subscription=subscription)
                  if provider["registrationState"] == "Registered"}
    for namespace in sorted(PROVIDERS):
        if namespace.casefold() in registered:
            continue
        print(f"Registering {namespace}.", file=sys.stderr, flush=True)
        az("provider", "register", "--namespace", namespace, "--wait", subscription=subscription)
    state_file = ROOT / ".provision" / f"{subscription}-{suffix}.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else None
    legacy_group = f"rg-foundry-bootcamp-{suffix}"
    if not state and az("group", "exists", "--name", legacy_group, subscription=subscription):
        existing = az("group", "show", "--name", legacy_group, subscription=subscription)
        state = {"location": existing["location"], "resourceGroupName": existing["name"]}
    regions = [state["location"]] if state else list(dict.fromkeys(locations))
    for location in regions:
        if not re.fullmatch(r"[a-z0-9]+", location):
            raise ValueError(f"Invalid Azure region: {location}")

    def finish(location, group, outputs):
        # Persist infrastructure success before ingestion, so failed ingestion resumes in place.
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({"location": location, "resourceGroupName": group}, indent=2))
        return {name: output["value"] for name, output in outputs.items()}

    if state:
        # Existing labs are updated in place and never deleted or moved.
        location, group = state["location"], state["resourceGroupName"]
        print(f"Updating {group} in {location}.", file=sys.stderr, flush=True)
        values = finish(location, group, deploy(suffix, location, group, subscription, principal_ids))
        seed(values, subscription, dataset_csv)
        print(json.dumps(values, indent=2))
        return

    fatal = []
    for start in range(0, len(regions), RACE_WIDTH):
        batch = regions[start:start + RACE_WIDTH]
        groups = {location: f"rg-foundry-bootcamp-{suffix}-{location}" for location in batch}
        leftovers = [group for group in groups.values()
                     if az("group", "exists", "--name", group, subscription=subscription)]
        if leftovers:
            raise RuntimeError(f"Untracked lab groups exist: {', '.join(leftovers)}. Delete them or "
                               "restore the .provision state file before provisioning again.")
        print(f"Racing deployments in {', '.join(batch)}; the first success is kept.",
              file=sys.stderr, flush=True)
        pool = ThreadPoolExecutor(max_workers=2 * len(batch))
        cleanups, winner = [], None
        try:
            attempts = {pool.submit(deploy, suffix, location, groups[location], subscription,
                                    principal_ids): location for location in batch}
            for attempt in as_completed(attempts):
                location = attempts[attempt]
                try:
                    outputs = attempt.result()
                except AzureError as error:
                    kind = "Capacity/region" if capacity_failure(str(error)) else "Non-retryable"
                    if kind == "Non-retryable":
                        fatal.append(error)
                    print(f"{kind} failure in {location}: {error}", file=sys.stderr, flush=True)
                    cleanups.append(pool.submit(remove_group, groups[location], subscription))
                    continue
                if winner:
                    cleanups.append(pool.submit(remove_group, groups[location], subscription))
                    continue
                print(f"Won in {location}; cancelling other regions.", file=sys.stderr, flush=True)
                winner = (location, groups[location], outputs)
                for other, other_location in attempts.items():
                    if not other.done():
                        pool.submit(cancel, suffix, other_location, groups[other_location], subscription)
            if winner:
                values = finish(*winner)
                seed(values, subscription, dataset_csv)  # Runs while extra labs are deleted.
        finally:
            failures = []
            for cleanup in cleanups:
                try:
                    cleanup.result()
                except (AzureError, RuntimeError) as error:
                    failures.append(str(error))
            pool.shutdown()
            if failures:
                raise RuntimeError("Extra lab cleanup failed: " + "; ".join(failures))
        if winner:
            print(json.dumps(values, indent=2))
            return
        if fatal:
            raise fatal[0]
    raise RuntimeError(f"Capacity exhausted in all requested regions: {', '.join(regions)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    deploy = commands.add_parser("provision")
    deploy.add_argument("--suffix", required=True)
    deploy.add_argument("--location", action="append")
    deploy.add_argument("--principal-id", action="append", default=[])
    load = commands.add_parser("seed")
    load.add_argument("--resource-group", required=True)
    load.add_argument("--deployment-name", required=True)
    for command in (deploy, load):
        command.add_argument("--subscription")
        command.add_argument("--dataset-csv")
    args = parser.parse_args()
    try:
        if args.command == "provision":
            locations = list(dict.fromkeys([*(args.location or []), *REGIONS]))
            provision(args.suffix, locations, args.subscription, args.principal_id, args.dataset_csv)
        else:
            outputs = az("deployment", "group", "show", "--resource-group", args.resource_group,
                         "--name", args.deployment_name, "--query", "properties.outputs",
                         subscription=args.subscription)
            seed({name: output["value"] for name, output in outputs.items()},
                 args.subscription, args.dataset_csv)
    except (AzureError, RuntimeError, ValueError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Deployment failed: {error}\n")


if __name__ == "__main__":
    main()
