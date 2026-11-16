# Foundry Bootcamp Template

Create your own hands-on AI workshop with **Microsoft Foundry** and
**Microsoft Agent Framework for Python**. This template provides a ready-to-deploy
Azure lab, a searchable IT support dataset, and paired challenge and solution
templates you can adapt to your scenario.

## Use this template

1. Select **Use this template > Create a new repository** on GitHub.
2. Open your new repository in **GitHub Codespaces**, or clone it and reopen it
   in a **VS Code Dev Container** (Docker required locally).
3. Sign in to Azure with `az login`, then run `./provision.sh` or, in
   PowerShell 7, `./provision.ps1` from the repository root.
4. Customize the [first challenge](challenges/challenge-01.md) and its
   [solution](walkthrough/challenge-01/solution-01.md), then update this README
   with your workshop's title, audience, and agenda.

Your Azure account needs permission to create resource groups, resources, and
role assignments. Review the [setup and deployment guide](docs/setup.md) for
prerequisites, subscription selection, participant access, and cleanup.
Provisioned resources incur Azure charges; new deployments can briefly use
capacity in three regions while selecting one lab.

## What's included

| Component | Purpose |
| --- | --- |
| Microsoft Foundry account and project | Foundation for your agent exercises |
| Azure AI Search | Full-text search over 100,000 IT support tickets |
| Blob Storage | Source CSV and dataset attribution |
| Application Insights and Log Analytics | Application telemetry and diagnostics |
| Python devcontainer | Python 3.13, uv, Agent Framework, Azure CLI, Bicep, and PowerShell |
| Workshop scaffolds | Participant challenges, matching solutions, and a wrap-up page |
| MicroHack hooks | Optional per-participant provisioning for managed events |

Services use Entra authentication, with access assigned to the principals you
supply (the signed-in deployment identity by default). **No models or completed
agent exercises are included.** Add model deployments and exercise code to suit
your workshop.

The [IT Support Tickets dataset](https://www.kaggle.com/datasets/ahsanneural/synthetic-it-support-tickets)
is by Muhammad Ahsan and licensed under **CC BY 4.0**. Provisioning downloads
version 1 and preserves attribution alongside the source data.

## Make it your own

Keep participant instructions in `challenges/` and matching solutions and assets
in `walkthrough/`. Duplicate the numbered challenge/solution pair for each
exercise, update navigation links, and adapt the [wrap-up page](challenges/finish.md).
The supplied pages are authoring scaffolds, not finished participant exercises.

Shared Azure resources and permissions live in `labautomation/main.bicep`.
Both standalone provisioning and the managed-event hooks use that template.
Keep downloaded data, credentials, and local deployment state out of Git.

## Guides

- [Setup, deployment, permissions, dataset loading, and cleanup](docs/setup.md)
- [Managed events and MicroHack platform integration](labautomation/README.md)
- [Local checks](docs/setup.md#local-checks)
- [Microsoft Agent Framework for Python](https://github.com/microsoft/agent-framework/tree/main/python)
