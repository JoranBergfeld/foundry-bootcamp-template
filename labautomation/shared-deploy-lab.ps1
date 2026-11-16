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

foreach ($namespace in @(
    'Microsoft.CognitiveServices', 'Microsoft.Search', 'Microsoft.Storage',
    'Microsoft.Insights', 'Microsoft.OperationalInsights'
)) {
    $provider = Get-AzResourceProvider -ProviderNamespace $namespace -ErrorAction Stop
    if ($provider.RegistrationState -notcontains 'Registered') {
        Write-Host "Registering $namespace in subscription '$SubscriptionId'."
        Register-AzResourceProvider -ProviderNamespace $namespace -ErrorAction Stop | Out-Null
        $deadline = [DateTime]::UtcNow.AddMinutes(10)
        do {
            $provider = Get-AzResourceProvider -ProviderNamespace $namespace -ErrorAction Stop
            if ($provider.RegistrationState -contains 'Registered') {
                break
            }
            if ([DateTime]::UtcNow -ge $deadline) {
                throw "Timed out waiting for $namespace registration."
            }
            Start-Sleep -Seconds 10
        } while ($true)
    }
}
