#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s [--location REGION] [--subscription ID_OR_NAME]\n' "$0"
}

location="westeurope"
subscription=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --location|--subscription)
            if [[ $# -lt 2 || -z "$2" || "$2" == -* ]]; then
                printf 'Error: %s requires a value.\n' "$1" >&2
                exit 1
            fi
            if [[ "$1" == "--location" ]]; then
                location="$2"
            else
                subscription="$2"
            fi
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            printf 'Error: unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if ! command -v az >/dev/null 2>&1; then
    printf 'Error: Azure CLI is required. Reopen this project in its devcontainer or install Azure CLI.\n' >&2
    exit 1
fi

account_args=(account show --output none)
if [[ -n "$subscription" ]]; then
    account_args+=(--subscription "$subscription")
fi
if ! az "${account_args[@]}"; then
    printf 'Error: cannot access the Azure subscription. Run az login and check your subscription.\n' >&2
    exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
suffix_file="$script_dir/.provision/suffix"

if [[ -e "$suffix_file" ]]; then
    suffix="$(cat "$suffix_file")"
    suffix="${suffix%$'\r'}"
else
    suffix="$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
    mkdir -p "$script_dir/.provision"
    printf '%s\n' "$suffix" > "$suffix_file"
fi

if [[ ! "$suffix" =~ ^[0-9a-f]{8}$ ]]; then
    printf 'Error: invalid suffix in %s; expected eight lowercase hexadecimal characters. Restore the original suffix to reuse your resource group.\n' "$suffix_file" >&2
    exit 1
fi

printf 'Provisioning rg-foundry-bootcamp-%s in %s\n' "$suffix" "$location"
deployment_args=(
    deployment sub create
    --name "foundry-bootcamp-$suffix"
    --location "$location"
    --template-file "$script_dir/main.bicep"
    --parameters "location=$location" "suffix=$suffix"
    --query properties.outputs
    --output json
)
if [[ -n "$subscription" ]]; then
    deployment_args+=(--subscription "$subscription")
fi
az "${deployment_args[@]}"
