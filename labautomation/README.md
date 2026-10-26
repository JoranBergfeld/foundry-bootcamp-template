# Lab automation

[Home](../README.md) | [Challenge template](../challenges/challenge-01.md)

Deploy a Microsoft Foundry account and project for each participant. No models,
datasets, or scenario-specific services are deployed.

## Folder layout

```text
labautomation/
|-- lab-defaults.json        # MicroHack platform settings
|-- deploy-lab.ps1           # Per-participant deployment hook
|-- shared-deploy-lab.ps1    # Once-per-subscription preparation
`-- main.bicep               # Shared resource-group-scoped Foundry template
```

## Standalone provisioning

From the repository root, run `./provision.sh` or `./provision.ps1`.
The root `main.bicep` creates a resource group and deploys this folder's
`main.bicep` into it. See [provisioning instructions](../README.md#provision).
Keep both templates together when distributing the repository.

## MicroHack platform deployment

The platform reads `lab-defaults.json`, prepares participant scopes and access,
then runs `shared-deploy-lab.ps1` once per subscription. This hook requests
registration of `Microsoft.CognitiveServices` if needed. Add future shared
preparation here; do not publish participant secrets from this hook.

The platform then invokes `deploy-lab.ps1` once per participant, with an
authenticated Azure context and its helper commands already loaded. These hooks
are not standalone provisioning scripts and are not invoked by the root scripts.

The participant hook accepts the standard `DeploymentType`, `SubscriptionId`,
`ResourceGroupName`, `PreferredLocation`, and `AllowedEntraUserIds` parameters.
It uses the platform-provided group for both resource-group deployment types.
For subscription deployments, it derives a stable participant group name with
`Get-MhhStableHash`. The active subscription must match `SubscriptionId`.

`Invoke-MhhDeploymentWithRegionFallback` deploys `main.bicep`, preserving
participant ownership and returning the actual region and template outputs.
Only after success does the hook publish the group name, region, Foundry
account/project names, and project endpoint as `HackboxCredential` values.
The account name is derived from the resource-group ID for isolation and
repeatable deployments.

**Region fallback can delete and recreate the participant resource group.**
Use these hooks only for disposable lab groups, not groups containing unrelated
resources. Foundry soft deletion can delay reuse of a deleted account name;
follow the Azure error guidance before retrying.

## Authoring guidance

- Add common infrastructure to `main.bicep` so both provisioning paths stay aligned.
- Keep resource locations based on the template's `location` parameter; do not
  pin it in the platform hook, which would defeat region fallback.
- The default is resource-group ownership, not subscription ownership.
  No extra role assignments or license groups are requested by this skeleton.
- Foundry uses Microsoft Entra authentication with local keys disabled. Resource
  ownership alone does not grant Foundry data-plane permissions; assign an
  appropriate Foundry role before adding agent exercises.
- The USD 1/day per-lab estimate is a planning placeholder, not a price quote.
  Recalculate it, subscription packing, regions, and license groups for your
  event. Model deployments and usage can incur additional costs.
- Delete the lab group after the event. Resource-group deletion also removes the
  Foundry account and project; soft-deleted accounts may remain recoverable.

See the [MicroHack platform contract](https://github.com/microsoft/MicroHack/blob/main/99-MicroHack-Template/labautomation/README.md)
for helper commands and hook requirements. Folder organization follows
[David's MicroHack](https://github.com/dsanchor/fraud-intelligence-microhack);
the files here contain generic bootcamp content only.
