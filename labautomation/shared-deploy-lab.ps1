[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SubscriptionId,

    [Parameter(Mandatory = $true)]
    [AllowEmptyCollection()]
    [string[]]$PreferredLocation = @(),

    [string[]]$AllowedEntraUserIds = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ((Get-AzContext).Subscription.Id -ne $SubscriptionId) {
    throw "The active Azure context must match subscription '$SubscriptionId'."
}

$provider = Get-AzResourceProvider -ProviderNamespace 'Microsoft.CognitiveServices' -ErrorAction Stop
if ($provider.RegistrationState -notcontains 'Registered') {
    Write-Host "Registering Microsoft.CognitiveServices in subscription '$SubscriptionId'."
    Register-AzResourceProvider -ProviderNamespace 'Microsoft.CognitiveServices' -ErrorAction Stop | Out-Null
}
