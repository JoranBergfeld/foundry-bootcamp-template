# Lab automation

[Home](../README.md) | [Challenge template](../challenges/challenge-01.md)

Deploy a Foundry account/project, Search Basic, private Blob Storage, and
workspace-based Application Insights for each participant. Load all 100,000
IT Support Tickets into Blob Storage and Search. No models are deployed.

## Folder layout

```text
labautomation/
|-- lab-defaults.json        # MicroHack platform settings
|-- deploy-lab.ps1           # Per-participant deployment hook
|-- shared-deploy-lab.ps1    # Once-per-subscription preparation
|-- main.bicep              # Shared resource-group-scoped environment template
`-- environment.py          # Shared provisioning and dataset ingestion (Python 3)
```

## Standalone provisioning

From the repository root, run `./provision.sh` or `./provision.ps1`.
The root `main.bicep` creates a resource group and deploys this folder's
`main.bicep` into it. See [provisioning instructions](../docs/setup.md#provision).
Keep both templates together when distributing the repository.

## MicroHack platform deployment

The platform reads `lab-defaults.json`, prepares participant scopes and access,
then runs `shared-deploy-lab.ps1` once per subscription. This hook requests
registration of `Microsoft.CognitiveServices`, `Microsoft.Search`,
`Microsoft.Storage`, `Microsoft.Insights`, and `Microsoft.OperationalInsights`
if needed. Add shared preparation here; do not publish participant secrets
from this hook.

The platform then invokes `deploy-lab.ps1` once per participant, with an
authenticated Azure context and its helper commands already loaded. These hooks
are not standalone provisioning scripts and are not invoked by the root scripts.

The runner needs Python 3 and Azure CLI, in addition to the platform's Az
PowerShell context. The participant hook accepts the standard `DeploymentType`, `SubscriptionId`,
`ResourceGroupName`, `PreferredLocation`, and `AllowedEntraUserIds` parameters.
It uses the platform-provided group for both resource-group deployment types.
For subscription deployments, it derives a stable participant group name with
`Get-MhhStableHash`. The active subscription must match `SubscriptionId`.

`Invoke-MhhDeploymentWithRegionFallback` deploys `main.bicep`, preserving
participant ownership and returning the actual region and template outputs.
All `AllowedEntraUserIds` are passed to Bicep for explicit service-scoped
control/data-plane roles. The deployment identity is also granted data access
for seeding. After infrastructure succeeds, `Update-MhhToken` refreshes the
platform's isolated Azure CLI login, then `environment.py seed` downloads
the pinned Kaggle version, uploads the raw CSV and attribution, indexes every
ticket, and verifies the 100,000-document count and a retrieval query.
Only after ingestion succeeds does the hook publish the group name, region,
Foundry, Search, Storage, and monitoring resource names/endpoints as
`HackboxCredential` values. Ingestion failure fails the hook rather than
publishing a success-shaped empty lab.
The account name is derived from the resource-group ID for isolation and
repeatable deployments.

The default ordered regions are `westeurope`, `swedencentral`, and `francecentral`.
The platform's helper classifies capacity/quota/unsupported-region failures and
tries another region; non-retryable failures stop. The platform owns a single
participant group, so its attempts stay sequential. The standalone scripts race
three regions in parallel and delete the extras; see
[regional provisioning](../docs/setup.md#provision).

**Region fallback can delete and recreate the participant resource group.**
Use these hooks only for disposable lab groups, not groups containing unrelated
resources. Foundry soft deletion can delay reuse of a deleted account name;
follow the Azure error guidance before retrying.

## Authoring guidance

- Add common infrastructure to `main.bicep` so both provisioning paths stay aligned.
- Keep resource locations based on the template's `location` parameter; do not
  pin it in the platform hook, which would defeat region fallback.
- The default is resource-group ownership, not subscription ownership; no license
  groups are requested. Participant roles and Foundry/Search identity permissions
  are defined in Bicep. See [resources and access](../docs/setup.md#resources-and-access).
- Foundry/Search use Entra authentication with local keys disabled. Storage
  shared keys and public blobs are disabled. The importer retries propagation
  delays and transient failures with bounded waits.
- The USD 5/day per-lab estimate is a planning placeholder, not a price quote.
  Recalculate it, subscription packing, regions, and license groups for your
  event. Model deployments and usage can incur additional costs.
- Delete the lab group after the event. Resource-group deletion also removes the
  Foundry account and project; soft-deleted accounts may remain recoverable.

See the [MicroHack platform contract](https://github.com/microsoft/MicroHack/blob/main/99-MicroHack-Template/labautomation/README.md)
for helper commands and hook requirements.
The scenario data is [IT Support Tickets](../docs/setup.md#it-support-tickets-dataset),
by Muhammad Ahsan, licensed CC BY 4.0. Keep attribution with dataset copies.
