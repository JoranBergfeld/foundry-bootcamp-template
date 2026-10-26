targetScope = 'subscription'

@description('Azure region for the bootcamp resource group and Foundry resources.')
param location string = 'westeurope'

@description('Random suffix generated and persisted by the provisioning scripts.')
@minLength(8)
@maxLength(8)
param suffix string

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-foundry-bootcamp-${suffix}'
  location: location
}

module foundry './labautomation/main.bicep' = {
  name: 'foundry-bootcamp'
  scope: resourceGroup
  params: {
    location: location
  }
}

output resourceGroupName string = resourceGroup.name
output resourceGroupId string = resourceGroup.id
output resourceGroupLocation string = resourceGroup.location
output foundryAccountName string = foundry.outputs.foundryAccountName
output foundryProjectName string = foundry.outputs.foundryProjectName
output foundryProjectEndpoint string = foundry.outputs.foundryProjectEndpoint
