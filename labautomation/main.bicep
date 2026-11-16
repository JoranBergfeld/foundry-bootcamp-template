targetScope = 'resourceGroup'

@description('Azure region for all lab resources.')
param location string = resourceGroup().location

@description('Entra object IDs of participants. The deployment identity also receives data access to seed the dataset.')
@minLength(1)
param principalIds array = [deployer().objectId]

var accountName = 'aif-bootcamp-${uniqueString(resourceGroup().id)}'
var resourceSuffix = uniqueString(resourceGroup().id)
var operators = union(principalIds, [deployer().objectId])
var foundryUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
var searchServiceRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
var searchDataRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
var blobDataRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
var monitoringReaderRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '43d0d8ad-25c7-4714-9337-8ba259a9fe05')
var metricsPublisherRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
var logReaderRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '73c42c96-874c-492b-b04d-ab87d138a893')

resource resourceReaders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in principalIds: {
  name: guid(resourceGroup().id, principalId, 'reader')
  properties: {
    principalId: principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'acdd72a7-3385-48ef-bd42-f606fba81ae7')
  }
}]

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: 'bootcamp'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Foundry Bootcamp'
    description: 'Project for bootcamp exercises.'
  }
}

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: 'srch-bootcamp-${resourceSuffix}'
  location: location
  sku: {
    name: 'basic'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    disableLocalAuth: true
    publicNetworkAccess: 'enabled'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stbootcamp${resourceSuffix}'
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource tickets 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: 'it-support-tickets'
  properties: {
    publicAccess: 'None'
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-bootcamp-${resourceSuffix}'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-bootcamp-${resourceSuffix}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    DisableLocalAuth: true
  }
}

resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'it-support-search'
  properties: {
    category: 'CognitiveSearch'
    authType: 'AAD'
    target: 'https://${search.name}.search.windows.net'
    metadata: {
      ApiType: 'Azure'
      ResourceId: search.id
    }
  }
}

resource storageConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'it-support-storage'
  properties: {
    category: 'AzureBlob'
    authType: 'AAD'
    target: storage.properties.primaryEndpoints.blob
    metadata: {
      ApiType: 'Azure'
      ResourceId: storage.id
      AccountName: storage.name
      ContainerName: tickets.name
    }
  }
}

resource insightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'bootcamp-insights'
  properties: {
    category: 'AppInsights'
    authType: 'ApiKey'
    target: insights.id
    credentials: {
      key: insights.properties.ConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: insights.id
    }
  }
}

resource foundryOperators 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in operators: {
  name: guid(account.id, principalId, foundryUserRole)
  scope: account
  properties: {
    principalId: principalId
    roleDefinitionId: foundryUserRole
  }
}]

resource searchOperators 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in operators: {
  name: guid(search.id, principalId, searchServiceRole)
  scope: search
  properties: {
    principalId: principalId
    roleDefinitionId: searchServiceRole
  }
}]

resource searchDataOperators 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in operators: {
  name: guid(search.id, principalId, searchDataRole)
  scope: search
  properties: {
    principalId: principalId
    roleDefinitionId: searchDataRole
  }
}]

resource blobOperators 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in operators: {
  name: guid(storage.id, principalId, blobDataRole)
  scope: storage
  properties: {
    principalId: principalId
    roleDefinitionId: blobDataRole
  }
}]

resource monitoringOperators 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in operators: {
  name: guid(insights.id, principalId, monitoringReaderRole)
  scope: insights
  properties: {
    principalId: principalId
    roleDefinitionId: monitoringReaderRole
  }
}]

resource telemetryOperators 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in operators: {
  name: guid(insights.id, principalId, metricsPublisherRole)
  scope: insights
  properties: {
    principalId: principalId
    roleDefinitionId: metricsPublisherRole
  }
}]

resource logOperators 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in operators: {
  name: guid(logs.id, principalId, logReaderRole)
  scope: logs
  properties: {
    principalId: principalId
    roleDefinitionId: logReaderRole
  }
}]

// Both identities can be used by Foundry tools; Search can read source blobs for future indexers.
var runtimePrincipals = [account.identity.principalId, project.identity.principalId]
var runtimeResources = [account.id, project.id]

resource runtimeSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, 2): {
  name: guid(search.id, runtimeResources[i], searchDataRole)
  scope: search
  properties: {
    principalId: runtimePrincipals[i]
    principalType: 'ServicePrincipal'
    roleDefinitionId: searchDataRole
  }
}]

resource runtimeSearchService 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, 2): {
  name: guid(search.id, runtimeResources[i], searchServiceRole)
  scope: search
  properties: {
    principalId: runtimePrincipals[i]
    principalType: 'ServicePrincipal'
    roleDefinitionId: searchServiceRole
  }
}]

resource runtimeStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, 2): {
  name: guid(storage.id, runtimeResources[i], blobDataRole)
  scope: storage
  properties: {
    principalId: runtimePrincipals[i]
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobDataRole
  }
}]

resource searchStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, search.id, 'blob-reader')
  scope: storage
  properties: {
    principalId: search.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
  }
}

resource runtimeTelemetry 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for i in range(0, 2): {
  name: guid(insights.id, runtimeResources[i], metricsPublisherRole)
  scope: insights
  properties: {
    principalId: runtimePrincipals[i]
    principalType: 'ServicePrincipal'
    roleDefinitionId: metricsPublisherRole
  }
}]

output foundryAccountName string = account.name
output foundryProjectName string = project.name
output foundryProjectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'
output searchServiceName string = search.name
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output searchIndexName string = 'it-support-tickets'
output storageAccountName string = storage.name
output storageBlobEndpoint string = storage.properties.primaryEndpoints.blob
output datasetContainerName string = tickets.name
output applicationInsightsName string = insights.name
output applicationInsightsConnectionString string = insights.properties.ConnectionString
output logAnalyticsWorkspaceName string = logs.name
