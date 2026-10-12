# Defender Tagging Logic App

An Azure Logic App (Consumption) that automatically tags devices in **Microsoft Defender for Endpoint** based on a set of rules, for example per asset domain for CTEM or SECaaS.

- Fetches all devices seen in the last month.
- Determines per device which tags it should have, based on the rules.
- Adds missing tags and removes tags that no longer apply, only when `RunMode = ReportAndTag`.
- Builds a CSV report with the current state and the changes per device.
- Uses a **system assigned managed identity**, so no passwords, secrets or connections.

## Files

| File | Contents |
|---|---|
| `template.json` | ARM template of the Logic App. **This is the main file.** |
| `parameters.example.json` | Example parameter file. Copy it per customer. |
| `Grant-DefenderPermissions.ps1` | Grants the Defender API permissions to the managed identity (once per tenant) |
| `automation-task/AutomationTaskTemplate.json` | Same workflow in Azure automation task template format. Kept for reference, not kept in sync with `template.json`. |

## How it works

### Schedule: full run and light run

The app runs every day at **02:00, 08:00, 12:00 and 16:00** (Belgian time, `Romance Standard Time`).

| Run | When | Which devices |
|---|---|---|
| **Full** | At `fullRunHour` (default 02:00), or when `ForceFullRun = true` | All devices. Tags are corrected. |
| **Light** | At all other hours | Only devices **without** an auto tag, CatchAll tag or manual tag, so new devices |

The light run is cheap because Defender only returns the new devices. The Logic App is billed per executed action, so every run over all devices costs money.

### Fetching devices

Devices are fetched in pages of `PageSize` (10,000) with `$top`/`$skip` until a page returns fewer devices. If a call to the Defender API fails (after the retry policy), paging stops and the run ends as **Failed** with error `FetchMachinesFailed`, so no partial report is created.

### Tag logic per device

1. **Manual tag present** (a tag from `manualTags`): the device gets **no** auto tags. Existing auto tags are removed.
2. **One or more rules match**: the device gets the tags of all matching rules.
3. **No rule matches**: the device gets the `catchAllTag`.

Only tags listed in the rules, plus the CatchAll tag, are managed. Any other tags on a device are always left alone.

### Why HTTP actions instead of the Defender connector

The Microsoft Defender ATP connector also supports managed identity. We still use plain HTTP actions with managed identity authentication because:

- **No API connection resource.** The connector needs a separate `Microsoft.Web/connections` resource per Logic App. With HTTP, the Logic App is the only resource in the ARM template.
- **Reliable paging.** It is not confirmed that the connector's pagination policy works for tenants with more than 10,000 devices. The HTTP version uses its own `$top`/`$skip` loop, so all devices are always fetched.
- **Same permissions.** Both options need the same Defender API permission on the managed identity (`Grant-DefenderPermissions.ps1`), so the connector gives no advantage there.

The trade-off is that the designer shows a URL and JSON body instead of the connector's form fields.

## Template parameters

Set per customer in the parameter file.

| Parameter | Default | Description |
|---|---|---|
| `logicAppName` | `Defender-Tagging` | Name of the Logic App |
| `location` | Resource group location | Azure region |
| `state` | `Disabled` | `Enabled` / `Disabled`. Keep `Disabled` until the permissions are set (see step 3). |
| `runMode` | `Report` | `Report`: report only. `ReportAndTag`: report and actually change tags. |
| `taggingRules` | SECAAS rules | The rules, see [Writing rules](#writing-rules) |
| `catchAllTag` | `CTEM-CatchAll` | Tag for devices that match no rule |
| `manualTags` | `CTEM_Manual_…` | Tags that exclude a device from automatic tagging |
| `fullRunHour` | `2` | Hour (Belgian time) of the full run: `2`, `8`, `12` or `16` |

The template passes these values to the workflow parameters (`RunMode`, `TaggingRules`, `CatchAllTag`, `ManualTags`, `FullRunHour`). The **Initialize_Variables** action reads them from there.

### Workflow variables

These are set in the **Initialize_Variables** action itself, not in the template parameters.

| Variable | Default | Description |
|---|---|---|
| `ForceFullRun` | `false` | `true` = every run is a full run. Useful for manual testing. |
| `PageSize` | `10000` | Number of devices per API call (Defender API maximum) |
| `Machines`, `Skip`, `MorePages`, `FetchFailed`, `FilterString`, `ReportRows` | | Internal, do not change |

## Writing rules

Each rule has a `tag`, an `assetDomain` (informational) and one or more conditions.

- Multiple conditions in one rule must **all** match (AND).
- Multiple rules with the same tag act as an OR.
- Comparisons are case-insensitive, except `lastIpAddress` and `machineTags`.

```json
{
  "tag": "SECAAS_WIN SRV",
  "assetDomain": "Hybrid cloud Windows",
  "computerDnsName": { "startsWith": "VSRV" },
  "osPlatform": { "startsWith": "WindowsServer" }
}
```

| Field | Supported operators |
|---|---|
| `computerDnsName` | `contains`, `startsWith`, `endsWith` |
| `osPlatform` | `contains`, `startsWith`, `endsWith`, `equals` |
| `rbacGroupName` | `contains`, `startsWith`, `endsWith`, `equals` |
| `lastIpAddress` | `startsWith` |
| `machineTags` | `equals` (device has this tag) |
| `onboardingStatus` | `equals` |
| `managedBy` | `equals` |
| `isAadJoined` | `equals` (`true` / `false`) |

Possible `osPlatform` values include: `Windows10`, `Windows11`, `WindowsServer2019`, `WindowsServer2022`, `Linux`, `Ubuntu`, `RedHatEnterpriseLinux`, `CentOS`, `Debian`, `macOS`, `iOS`, `Android`.

## Deploying to a customer

### 1. Prepare the parameter file

Copy `parameters.example.json` to e.g. `customerX.parameters.json` and set the name, rules and tags for the customer. Leave `state` on `Disabled` and `runMode` on `Report`.

> Customer parameter files contain customer-specific names. Keep them out of public repositories.

### 2. Deploy the template

**Azure CLI:**

```powershell
az login --tenant <tenant>.onmicrosoft.com
az deployment group create -g <resource-group> --template-file template.json --parameters customerX.parameters.json --query properties.outputs.principalId.value -o tsv
```

**Azure PowerShell:**

```powershell
Connect-AzAccount -Tenant <tenant>.onmicrosoft.com
(New-AzResourceGroupDeployment -ResourceGroupName <resource-group> -TemplateFile template.json -TemplateParameterFile customerX.parameters.json).Outputs.principalId.Value
```

**Portal:** search for **Deploy a custom template** → **Build your own template in the editor** → **Load file** → `template.json` → **Save**. Fill in the parameters (or **Edit parameters** → **Load file** → your parameter file) → **Review + create**. The Object ID is shown under **Outputs** of the deployment.

All three return the **Object (principal) ID** of the managed identity. You can also find it in the Logic App → **Identity** → **System assigned**.

### 3. Grant Defender permissions

To be run by a Global Administrator or Privileged Role Administrator of the customer:

```powershell
.\Grant-DefenderPermissions.ps1 -PrincipalId <object-id> -TenantId <tenant>.onmicrosoft.com
```

The script grants `Machine.ReadWrite.All` (WindowsDefenderATP) to the identity. It installs the `Microsoft.Graph.Applications` module if needed.

If PowerShell blocks the script (*"running scripts is disabled on this system"*), allow it for the current window only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

> [!WARNING]
> **Wait at least 15 minutes after running the script before enabling the Logic App.** The new permission needs a few minutes to propagate in Entra ID.
>
> If the Logic App runs too early, it gets a token **without** the role. Azure runs Logic Apps on multiple servers, and each server caches its own token for **up to 24 hours**. As a result, runs can fail with `403 Forbidden` (`FetchMachinesFailed`) at random for up to 24 hours, even though the permission is set correctly. Some runs succeed, others fail, depending on the server they land on.
>
> This resolves itself once the cached tokens expire. That is why the template deploys the Logic App as `Disabled` by default.

### 4. Enable and test

1. Logic App → **Overview** → **Enable**.
2. In the designer, set the variable `ForceFullRun = true` → **Save** → **Run** → **Run**.
3. Open the run and check the output of **Create_CSV_table**. That is the report.
4. Set `ForceFullRun` back to `false`.

### 5. Switch on tagging

If the report looks right, set `runMode` to `ReportAndTag` in the parameter file and deploy again (step 2, with `state` set to `Enabled`).

> Redeploying overwrites changes made in the portal. Make changes in the parameter file or `template.json`, not only in the designer.

## Report

The report is available as CSV in the **run history**, in the `Create_CSV_table` action. One row per device:

| Column | Contents |
|---|---|
| `Status` | `Change` (something needs to change) or `NoChange` |
| `MachineId`, `computerDnsName`, `osPlatform`, `lastIpAddress`, `rbacGroupName`, `onboardingStatus`, `isAadJoined`, `managedBy` | Device details from Defender |
| `machineTags` | All tags before the run |
| `Manualtags` | Manual tags on the device |
| `ExistingTags` | Existing auto tags |
| `TagToAdd`, `TagToRemove` | Proposal |
| `TagAddedSuccess`, `TagRemovedSuccess` | What actually succeeded (only with `ReportAndTag`) |

## Costs

- **Logic App:** billed per action, about 10 actions per device per run. A full run over 5,000 devices costs about $1.25. Light runs cost cents.
- **Defender API:** free. Limit is 100 calls per minute and 1,500 per hour. On a 429 error the app retries automatically.

## Troubleshooting

| Error | Cause / fix |
|---|---|
| `Could not find member 'connections'` when saving in code view | You pasted `automation-task/AutomationTaskTemplate.json` into the code view. Deploy `template.json` instead (step 2). |
| `401 Unauthorized` on HTTP actions | The managed identity is not enabled. The template enables it; check Logic App → **Identity**. |
| Run fails with `FetchMachinesFailed`, `HTTP - Get machines` returns `403 Forbidden` with *"Missing application roles … application roles: ."* | The token has no roles. Either the script from step 3 was not run, or the Logic App ran before the permission had propagated. In the latter case, tokens without the role stay cached on some Azure servers for up to 24 hours, so runs fail at random (some succeed, some fail) until they expire. Check the permission (next row). If it is assigned, wait up to 24 hours. See the warning in step 3. |
| Check if the permission is assigned | Entra ID → Enterprise applications → filter *Managed Identities* → the Logic App → **Permissions** → should list WindowsDefenderATP `Machine.ReadWrite.All`. |
| `running scripts is disabled on this system` | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first (see step 3). |
| `429 Too Many Requests` | Defender API rate limit reached. The app retries by itself. With many changes, the run simply takes longer. |
| Light run still picks up many devices | Those devices don't have a tag from the rules yet. They will be tagged after the next full run. |
