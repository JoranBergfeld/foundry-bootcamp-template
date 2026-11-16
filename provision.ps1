[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$Location = 'westeurope',

    [ValidateNotNullOrEmpty()]
    [string]$Subscription,

    [string[]]$PrincipalId = @(),

    [string]$DatasetCsv
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI is required. Reopen this project in its devcontainer or install Azure CLI.'
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is required. Reopen this project in its devcontainer or install uv.'
}

$subscriptionArgs = @()
if ($Subscription) {
    $subscriptionArgs = @('--subscription', $Subscription)
}

& az account show @subscriptionArgs --output none
if ($LASTEXITCODE -ne 0) {
    throw 'Cannot access the Azure subscription. Run az login and check your subscription.'
}

$stateDirectory = Join-Path $PSScriptRoot '.provision'
$suffixFile = Join-Path $stateDirectory 'suffix'

if (Test-Path -LiteralPath $suffixFile) {
    $suffix = [System.IO.File]::ReadAllText($suffixFile).TrimEnd([char[]]"`r`n")
} else {
    $suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)
    New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
    [System.IO.File]::WriteAllText($suffixFile, "$suffix`n")
}

if ($suffix -cnotmatch '^[0-9a-f]{8}$') {
    throw "Invalid suffix in ${suffixFile}; expected eight lowercase hexadecimal characters. Restore the original suffix to reuse your resource group."
}

$deploymentArgs = @(
    'run', '--no-project', '--python', '3.13', 'python'
    (Join-Path $PSScriptRoot 'labautomation/environment.py')
    'provision', '--suffix', $suffix, '--location', $Location
)
if ($Subscription) {
    $deploymentArgs += @('--subscription', $Subscription)
}
foreach ($id in $PrincipalId) {
    $deploymentArgs += @('--principal-id', $id)
}
if ($DatasetCsv) {
    $deploymentArgs += @('--dataset-csv', $DatasetCsv)
}
& uv @deploymentArgs
if ($LASTEXITCODE -ne 0) {
    throw 'Deployment failed. Resolve the Azure CLI error above and rerun this script.'
}
