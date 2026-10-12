<#
.SYNOPSIS
    Grants the Logic App's system assigned managed identity access to the Defender for Endpoint API.

.DESCRIPTION
    Run once per tenant, by a Global Administrator or Privileged Role Administrator.
    Assigns the application permission Machine.ReadWrite.All (WindowsDefenderATP) to the managed identity,
    so the Logic App can list machines and add/remove tags.

.PARAMETER PrincipalId
    Object (principal) ID of the managed identity. Logic App > Identity > System assigned > Object (principal) ID.

.PARAMETER TenantId
    Tenant ID of the customer.

.EXAMPLE
    .\Grant-DefenderPermissions.ps1 -PrincipalId 11111111-2222-3333-4444-555555555555 -TenantId contoso.onmicrosoft.com
#>
param(
    [Parameter(Mandatory)][string]$PrincipalId,
    [Parameter(Mandatory)][string]$TenantId
)

$ErrorActionPreference = 'Stop'
$DefenderAppId = 'fc780465-2017-40d4-a0c5-307022471b92'   # WindowsDefenderATP
$Permissions   = @('Machine.ReadWrite.All')

if (-not (Get-Module -ListAvailable Microsoft.Graph.Applications)) {
    Install-Module Microsoft.Graph.Applications -Scope CurrentUser -Force
}
Connect-MgGraph -TenantId $TenantId -Scopes 'Application.Read.All', 'AppRoleAssignment.ReadWrite.All' -NoWelcome

$identity = Get-MgServicePrincipal -ServicePrincipalId $PrincipalId
$defender = Get-MgServicePrincipal -Filter "appId eq '$DefenderAppId'"
if (-not $defender) { throw "WindowsDefenderATP service principal not found. Is Defender for Endpoint enabled in this tenant?" }

$existing = Get-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $identity.Id -All

foreach ($perm in $Permissions) {
    $role = $defender.AppRoles | Where-Object { $_.Value -eq $perm -and $_.AllowedMemberTypes -contains 'Application' }
    if ($existing | Where-Object { $_.AppRoleId -eq $role.Id -and $_.ResourceId -eq $defender.Id }) {
        Write-Host "$perm already assigned to $($identity.DisplayName)"
        continue
    }
    New-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $identity.Id -PrincipalId $identity.Id -ResourceId $defender.Id -AppRoleId $role.Id | Out-Null
    Write-Host "$perm assigned to $($identity.DisplayName)"
}

Disconnect-MgGraph | Out-Null
