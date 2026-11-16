[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('subscription', 'resourcegroup', 'resourcegroup-with-subscriptionowner')]
    [string]$DeploymentType,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SubscriptionId,

    [string]$ResourceGroupName = '',

    [string[]]$PreferredLocation = @(),

    [string[]]$AllowedEntraUserIds = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ((Get-AzContext).Subscription.Id -ne $SubscriptionId) {
    throw "The active Azure context must match subscription '$SubscriptionId'."
}
if ($AllowedEntraUserIds.Count -eq 0 -or
    @($AllowedEntraUserIds | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -gt 0) {
    throw 'AllowedEntraUserIds must contain non-empty participant object IDs.'
}
if ($DeploymentType -eq 'subscription') {
    $suffix = Get-MhhStableHash $AllowedEntraUserIds -Length 12
    $ResourceGroupName = "rg-foundry-bootcamp-$suffix"
} elseif ([string]::IsNullOrWhiteSpace($ResourceGroupName)) {
    throw "ResourceGroupName is required for deployment type '$DeploymentType'."
}
if ($PreferredLocation.Count -eq 0) {
    $PreferredLocation = @('westeurope', 'swedencentral', 'francecentral')
}
$python = Get-Command python3, python -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $python) {
    throw 'Python 3 is required to load the IT Support Tickets dataset.'
}

$result = Invoke-MhhDeploymentWithRegionFallback `
    -PreferredLocations $PreferredLocation `
    -ResourceGroupName $ResourceGroupName `
    -RgOwnerEntraObjectIds $AllowedEntraUserIds `
    -TemplateFile (Join-Path $PSScriptRoot 'main.bicep') `
    -TemplateParameterObject @{ principalIds = $AllowedEntraUserIds } `
    -DeploymentNamePrefix 'foundry-bootcamp'

Update-MhhToken | Out-Null
& $python (Join-Path $PSScriptRoot 'environment.py') seed `
    --subscription $SubscriptionId --resource-group $ResourceGroupName `
    --deployment-name $result.DeploymentName
if ($LASTEXITCODE -ne 0) {
    throw 'IT Support Tickets ingestion failed; no lab credentials will be published.'
}

@{ HackboxCredential = @{
    name = 'ResourceGroupName'; value = $ResourceGroupName; note = 'Bootcamp resource group'
} }
@{ HackboxCredential = @{
    name = 'EffectiveLocation'; value = $result.LocationUsed; note = 'Successful deployment region'
} }
@{ HackboxCredential = @{
    name = 'FoundryAccountName'; value = $result.Outputs.foundryAccountName; note = 'Foundry account'
} }
@{ HackboxCredential = @{
    name = 'FoundryProjectName'; value = $result.Outputs.foundryProjectName; note = 'Foundry project'
} }
@{ HackboxCredential = @{
    name = 'FoundryProjectEndpoint'; value = $result.Outputs.foundryProjectEndpoint; note = 'Project API endpoint'
} }
foreach ($name in @(
    'searchServiceName', 'searchEndpoint', 'searchIndexName', 'storageAccountName',
    'datasetContainerName', 'applicationInsightsName', 'logAnalyticsWorkspaceName'
)) {
    @{ HackboxCredential = @{
        name = $name; value = $result.Outputs[$name]; note = 'Bootcamp resource'
    } }
}
