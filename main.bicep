targetScope = 'subscription'

@description('Azure region for the bootcamp resource group and Foundry resources.')
param location string = 'westeurope'

@description('Random suffix generated and persisted by the provisioning scripts.')
@minLength(8)
@maxLength(8)
param suffix string

@description('Entra object IDs of participants; defaults to the deployment identity.')
@minLength(1)
param principalIds array = [deployer().objectId]

@description('Override used by standalone regional fallback to isolate each attempt.')
param resourceGroupName string = 'rg-foundry-bootcamp-${suffix}'

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
}

module foundry './labautomation/main.bicep' = {
  name: 'foundry-bootcamp'
  scope: resourceGroup
  params: {
    location: location
    principalIds: principalIds
  }
}

output resourceGroupName string = resourceGroup.name
output resourceGroupId string = resourceGroup.id
output resourceGroupLocation string = resourceGroup.location
output foundryAccountName string = foundry.outputs.foundryAccountName
output foundryProjectName string = foundry.outputs.foundryProjectName
output foundryProjectEndpoint string = foundry.outputs.foundryProjectEndpoint
output searchServiceName string = foundry.outputs.searchServiceName
output searchEndpoint string = foundry.outputs.searchEndpoint
output searchIndexName string = foundry.outputs.searchIndexName
output storageAccountName string = foundry.outputs.storageAccountName
output storageBlobEndpoint string = foundry.outputs.storageBlobEndpoint
output datasetContainerName string = foundry.outputs.datasetContainerName
output applicationInsightsName string = foundry.outputs.applicationInsightsName
output applicationInsightsConnectionString string = foundry.outputs.applicationInsightsConnectionString
output logAnalyticsWorkspaceName string = foundry.outputs.logAnalyticsWorkspaceName
