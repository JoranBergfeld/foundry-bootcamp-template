# Foundry Bootcamp Template

Provision **Microsoft Foundry, Azure AI Search, Application Insights and Blob
Storage**, with a searchable IT support dataset, then build agents using
Microsoft Agent Framework for Python. No models are deployed.

## Workshop structure

The folder layout follows [David's MicroHack](https://github.com/dsanchor/fraud-intelligence-microhack),
without its fraud-specific content.

```text
labautomation/                  # Platform hooks and shared Foundry infrastructure
challenges/
|-- challenge-01.md              # Participant-facing challenge template
`-- finish.md                    # Wrap-up and cleanup
walkthrough/
`-- challenge-01/
    `-- solution-01.md           # Matching solution template and future assets
```

Start with the [challenge template](challenges/challenge-01.md) and its
[solution template](walkthrough/challenge-01/solution-01.md). Both are authoring
scaffolds, not completed exercises. Duplicate the pair when adding challenges,
keeping their numbering and navigation links aligned.

For managed events, see [lab automation](labautomation/README.md).

## Development environment

Open this repository in VS Code with the **Dev Containers** extension and choose
**Dev Containers: Reopen in Container**, or open it in GitHub Codespaces.
Local devcontainers require Docker.

The container includes Python 3.13, uv, Azure CLI, Bicep, and PowerShell.
Container creation runs `uv sync --locked` to install Microsoft Agent Framework
into `.venv`. VS Code uses that environment automatically.

Without a devcontainer, install Python 3.13, [uv](https://docs.astral.sh/uv/),
[Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), and Bicep
(`az bicep install`), then run `uv sync --locked`. PowerShell 7 is required only
for the PowerShell provisioning script.

Use `uv run python` for bootcamp exercises. The lockfile captures the latest
stable `agent-framework` release available when this template was created. To
upgrade later, run `uv lock --upgrade && uv sync --locked` and commit `uv.lock`.
See the [official Python guide](https://github.com/microsoft/agent-framework/tree/main/python)
for framework usage.

## Provision

Sign in using `az login` (or `az login --use-device-code` in a headless
environment). Your account needs subscription-level permissions to create
resource groups, deployments, and role assignments, such as **Owner**, or
**Contributor + Role Based Access Control Administrator** at subscription scope.
Standalone provisioning uses the root `main.bicep` at subscription scope, which
creates the group and calls the shared `labautomation/main.bicep` template.
All services must be available in the selected region.

**Bash** (Linux, macOS, or WSL):

```bash
./provision.sh
# Optional overrides:
./provision.sh --subscription "<subscription-id-or-name>" --location swedencentral
# Grant another principal access (Entra object ID, not application/client ID):
./provision.sh --principal-id "<object-id>"
```

**PowerShell 7**:

```powershell
./provision.ps1
# Optional overrides:
./provision.ps1 -Subscription "<subscription-id-or-name>" -Location swedencentral
# Multiple participants:
./provision.ps1 -PrincipalId "<object-id-1>", "<object-id-2>"
```

Both entry points require uv and run the same Python 3.13 provisioning/ingestion
code, without installing the exercise dependencies. Without a subscription
argument they use the current Azure CLI subscription, never changing its default.
They print resource names and endpoints only after dataset ingestion succeeds.

The first region is `westeurope` (or your override), followed by untried regions
from `westeurope`, `swedencentral`, and `francecentral`. A new lab races up to
three regions in parallel, each in `rg-foundry-bootcamp-<suffix>-<region>`. The
first successful deployment wins: still-running attempts are cancelled, and every
other group created by the race is deleted (with deletion verified and soft-deleted
Foundry accounts purged) while the dataset loads into the winner. This briefly
consumes up to three times the quota but reaches a single lab quickly. If every
attempt hits capacity, regional quota, or unsupported-region errors, the next
three regions are tried; if any failed with an RBAC, policy, template, or unknown
error and none succeeded, that error is raised. **Pre-existing, untracked lab
groups are never deployed into or deleted**; provisioning stops instead.

The shared suffix is stored in `.provision/suffix`, and the successful region/group
in `.provision/<subscription-id>-<suffix>.json`. Preserve both ignored files when
moving machines to resume the same environment. Reruns keep the winning region,
even if a different location is requested, and upsert the same ticket IDs. An
ingestion failure leaves successful infrastructure in place for retry.
An older `rg-foundry-bootcamp-<suffix>` group from the original template is
detected and upgraded in place rather than creating a second lab.

### Resources and access

The shared template deploys a Foundry account/project, Search Basic (one replica,
one partition), Standard LRS Storage with a private `it-support-tickets` container,
and workspace-based Application Insights with a 30-day Log Analytics workspace.
Search, Storage, and Application Insights connections are attached to the project.
These are public-network lab endpoints with Entra authentication; Foundry/Search
local keys, Storage shared keys/public blobs, and unauthenticated telemetry
ingestion are disabled.

Every supplied principal receives resource-group **Reader** for discovery, plus
**Foundry User**, **Search Service Contributor**,
**Search Index Data Contributor**, **Storage Blob Data Contributor**,
**Monitoring Reader**, **Monitoring Metrics Publisher**, and **Log Analytics
Reader**, scoped to the corresponding resources. The deployment identity receives
the same access so it can seed the data, including when participants differ from
the deployer. Foundry account/project managed identities receive Search
schema/data, Blob data, and telemetry publishing access; Search's identity can
read blobs.
These assignments are deterministic and do not grant subscription ownership.
Application Insights' connection stores its connection string in Foundry's
credential store; exporters must still use an Entra credential for ingestion.

### IT Support Tickets dataset

Every successful deployment downloads **version 1** of Muhammad Ahsan's
[`ahsanneural/synthetic-it-support-tickets`](https://www.kaggle.com/datasets/ahsanneural/synthetic-it-support-tickets)
from Kaggle. It validates all **100,000 rows and 20 columns**, uploads the unchanged
CSV plus `attribution.json` (creator, source, CC BY 4.0 license, version, SHA-256,
row count, and transformation note), and loads all tickets into Search index
`it-support-tickets`. All columns are retained; dates, nullable resolution times,
and boolean flags are converted to Search types. Text is full-text searchable;
metadata supports filtering. No embeddings/model quota is required.

Indexing uses bounded batches and idempotent `mergeOrUpload`, checks per-document
errors, waits for RBAC propagation and searchable document counts, and verifies a
retrieval query before declaring success. This is a disposable lab index, not an
import target for unrelated documents.

If Kaggle requires interactive download in your environment, obtain version 1
from the source page and pass `--dataset-csv "<path>"` (Bash) or
`-DatasetCsv "<path>"` (PowerShell). Do not put Kaggle credentials or downloaded
data in Git. For dataset-only retry, use the resource-group deployment name
(`foundry-bootcamp` for standalone provisioning):

```powershell
uv run --no-project --python 3.13 python labautomation/environment.py seed `
  --subscription "<subscription-id>" --resource-group "<printed-group>" `
  --deployment-name foundry-bootcamp
```

## Cleanup

Delete the group when finished, substituting its printed name:

```bash
az group delete --name "<printed-group>" --subscription "<subscription-id>"
```

This deletes **all resources in the group**, including anything added during the
bootcamp. Keep `.provision/` to reuse the same name and region later. Remove it
only when you intentionally want the next run to create a differently named
group; removing it does not delete Azure resources. Foundry accounts are
soft-deleted and may require recovery or purging before their names can be
reused; follow Azure's error guidance if redeployment reports a name conflict.

## Local checks

```bash
python3 -m unittest discover -s tests -v
az bicep build --file main.bicep --stdout
az bicep build --file labautomation/main.bicep --stdout
```

The tests mock Azure and HTTP operations and never deploy Azure resources.
They test Bash on Unix and PowerShell when installed, including shared suffix
state, participant permissions, hook failure handling, ingestion validation and
regional fallback/cleanup. Template tests compile both deployment paths when
`bicep` or `az bicep` is available. These checks do not replace live validation.
