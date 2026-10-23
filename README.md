# Foundry Bootcamp Template

A minimal starting point for the bootcamp: provision **one empty Azure resource
group**, then build agents using Microsoft Agent Framework for Python.
No Foundry projects, models, or other Azure services are deployed.

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
resource groups and deployments, such as the **Contributor** role.
Provisioning always uses the root `main.bicep` at subscription scope.

**Bash** (Linux, macOS, or WSL):

```bash
./provision.sh
# Optional overrides:
./provision.sh --subscription "<subscription-id-or-name>" --location swedencentral
```

**PowerShell 7**:

```powershell
./provision.ps1
# Optional overrides:
./provision.ps1 -Subscription "<subscription-id-or-name>" -Location swedencentral
```

The default region is `westeurope`. Without a subscription argument, the scripts
use your current Azure CLI subscription. They never change that CLI default.
The deployment prints the resource group's name, ID, and location.

Both scripts generate `rg-foundry-bootcamp-<8-character-random-suffix>` and share
the suffix stored in `.provision/suffix`. Reruns in the same subscription reuse
that group, even when switching shells. Preserve this ignored file when moving
between machines or recreating a Codespace if you want to reuse the same group.
Using another subscription creates the same group name in that subscription.
Do not change the region on reruns: Azure cannot move an existing resource group
to another region.

## Cleanup

Delete the group when finished, substituting its printed name:

```bash
az group delete --name rg-foundry-bootcamp-<your-suffix> --subscription "<subscription-id>"
```

This deletes **all resources in the group**, including anything added during the
bootcamp. Keep `.provision/suffix` to reuse the name later. Remove that file
only when you intentionally want the next run to create a differently named
group; removing it does not delete Azure resources.

## Local checks

```bash
python3 -m unittest discover -s tests -v
az bicep build --file main.bicep --stdout
```

The script tests use a mocked Azure CLI and temporary state; they do not deploy
Azure resources. They test Bash plus PowerShell when `pwsh` is installed.
