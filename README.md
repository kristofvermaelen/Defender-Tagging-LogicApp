# Defender Tagging Logic App

An Azure Logic App (Consumption) that automatically tags devices in **Microsoft Defender for Endpoint** based on a set of rules, for example per asset domain for CTEM or SECaaS.

- Fetches all devices seen in the last 7 days.
- Determines per device which tags it should have, based on the rules.
- Adds missing tags and removes tags that no longer apply, only when `RunMode = ReportAndTag`.
- Builds a CSV report with the current state and the changes per device.
- Uses a **system assigned managed identity**, so no passwords, secrets or connections.

## Files

| File | Contents |
|---|---|
| `AutomationTaskTemplate.json` | The full Logic App (template format) |
| `Grant-DefenderPermissions.ps1` | Grants the Defender API permissions to the managed identity (once per tenant) |

## How it works

### Schedule: full run and light run

The app runs every day at **02:00, 08:00, 12:00 and 16:00** (Belgian time, `Romance Standard Time`).

| Run | When | Which devices |
|---|---|---|
| **Full** | At `FullRunHour` (default 02:00), or when `ForceFullRun = true` | All devices. Tags are corrected. |
| **Light** | At all other hours | Only devices **without** an auto tag, CatchAll tag or manual tag, so new devices |

The light run is cheap because Defender only returns the new devices. The Logic App is billed per executed action, so every run over all devices costs money.

### Tag logic per device

1. **Manual tag present** (a tag from `ManualTags`): the device gets **no** auto tags. Existing auto tags are removed.
2. **One or more rules match**: the device gets the tags of all matching rules.
3. **No rule matches**: the device gets the `CatchAllTag`.

Only tags listed in the rules, plus the CatchAll tag, are managed. Any other tags on a device are always left alone.

## Variables

All variables are in the **Initialize_Variables** action.

| Variable | Default | Description |
|---|---|---|
| `RunMode` | `Report` | `Report`: report only. `ReportAndTag`: report and actually change tags. |
| `CTEM_Tagging_Rules` | | The rules, see below |
| `CatchAllTag` | `CTEM-CatchAll` | Tag for devices that match no rule |
| `ManualTags` | `CTEM_Manual_…` | Tags that exclude a device from automatic tagging |
| `FullRunHour` | `2` | Hour (Belgian time) of the full run. Must be one of the scheduled hours. |
| `ForceFullRun` | `false` | `true` = every run is a full run. Useful for manual testing. |
| `PageSize` | `10000` | Number of devices per API call (Defender API maximum) |
| `Machines`, `Skip`, `MorePages`, `FilterString`, `ReportRows` | | Internal, do not change |

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

### 1. Create the Logic App

Create a **Logic App (Consumption)** in the customer tenant.

### 2. Paste the code

The Logic App code view does **not** accept the full `AutomationTaskTemplate.json`. If you paste it, saving fails with *"Could not find member 'connections'"*. Paste only the `definition` and `parameters` part. To extract it:

```powershell
$j = Get-Content .\AutomationTaskTemplate.json -Raw | ConvertFrom-Json
@{ definition = $j.data.definition; parameters = @{} } | ConvertTo-Json -Depth 100 | Set-Clipboard
```

Then go to the Logic App → **Logic app code view** → **Ctrl+A**, **Ctrl+V** → **Save**.

### 3. Enable the managed identity

Logic App → **Identity** → **System assigned** → **On** → **Save**. Copy the **Object (principal) ID**.

### 4. Grant Defender permissions

To be run by a Global Administrator or Privileged Role Administrator of the customer:

```powershell
.\Grant-DefenderPermissions.ps1 -PrincipalId <object-id> -TenantId <tenant>.onmicrosoft.com
```

The script grants `Machine.ReadWrite.All` (WindowsDefenderATP) to the identity. It installs the `Microsoft.Graph.Applications` module if needed.

### 5. Set rules and variables

Adjust `CTEM_Tagging_Rules`, `CatchAllTag` and `ManualTags` for the customer. Leave `RunMode` on `Report` for now.

### 6. Test

1. Set `ForceFullRun = true` and click **Run** → **Run**.
2. Open the run and check the output of **Create_CSV_table**. That is the report.
3. If the proposal looks right, set `RunMode = ReportAndTag` and `ForceFullRun = false`.

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
| `Could not find member 'connections'` on Save | You pasted the full template file. Paste only `definition` and `parameters` (see step 2). |
| `401 Unauthorized` / `403 Forbidden` on HTTP actions | The managed identity is not enabled, or the script from step 4 has not been run yet. After granting, it can take up to 30 minutes to take effect. |
| `429 Too Many Requests` | Defender API rate limit reached. The app retries by itself. With many changes, the run simply takes longer. |
| Light run still picks up many devices | Those devices don't have a tag from the rules yet. They will be tagged after the next full run. |
