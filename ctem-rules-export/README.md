# CTEM rules export

`ctem_rules_to_json_with_domains.py` converts the **Rules** sheet of a filled CTEM tagging workbook (`.xlsx`) into the JSON format that the Logic App expects in the `taggingRules` parameter.

The customer (or consultant) maintains the rules in Excel. The script validates them and produces the `{ "rules": [...] }` object, so nobody has to write the JSON by hand.

## Files

| File | Contents |
|---|---|
| `CTEM_Tagging_Rules_template.xlsx` | Empty workbook for the customer, with the sheets **Rules** (to fill in), **Instructions**, **Examples** and **Asset Domains** |
| `ctem_rules_to_json_with_domains.py` | Converts the filled **Rules** sheet to `taggingRules` JSON |

## Requirements

- Python **3.9+**
- No extra packages. The script uses only the standard library and reads the `.xlsx` file directly, so Excel does not have to be installed.

## Usage

```powershell
python ctem_rules_to_json_with_domains.py <workbook.xlsx> [-o <output.json>]
```

| Argument | Description |
|---|---|
| `workbook` | The filled `.xlsx` template |
| `-o`, `--output` | Output file. Default: the workbook name with `.json` (e.g. `customerX.xlsx` → `customerX.json`) |

Example:

```powershell
python ctem_rules_to_json_with_domains.py .\customerX-ctem-tagging.xlsx -o .\customerX-rules.json
# Wrote 12 rule(s) to customerX-rules.json
```

On error, the script prints `Error: <reason>` and exits with code 1. No output file is written in that case.

## Workbook format

The workbook must contain a sheet named **`Rules`**. The headers must be in **row 1**, in exactly this order. Two template versions are accepted.

| Column | Original template | Template with asset domain |
|---|---|---|
| A | `tag` | `tag` |
| B | *(filters start here)* | `assetDomain` |
| next | filter columns (see below) | filter columns (see below) |

Filter columns, in order:

```
computerDnsName.contains   computerDnsName.startsWith   computerDnsName.endsWith
osPlatform.contains        osPlatform.startsWith        osPlatform.endsWith        osPlatform.equals
lastIpAddress.startsWith
rbacGroupName.contains     rbacGroupName.startsWith     rbacGroupName.endsWith     rbacGroupName.equals
machineTags.equals
onboardingStatus.equals
managedBy.equals
isAadJoined.equals
```

These columns correspond 1:1 with the fields and operators that the Logic App supports. See [Writing rules](../README.md#writing-rules) in the main README.

### Allowed `assetDomain` values

`Hybrid cloud Linux/Unix`, `Hybrid cloud Windows`, `Hybrid cloud Other`, `Network`, `Workplace`, `OT`, `IOT`, `SaaS`

### Filling in rules

- **One row = one rule.** All filled filter cells in a row must match (AND).
- **The same tag on several rows** acts as an OR, the same as in the Logic App.
- **Empty cells** are ignored. Completely empty rows are skipped.
- **Values are trimmed**, so leading and trailing spaces are removed.
- **`isAadJoined.equals`** must be `true` or `false`. It is written to the JSON as a boolean.
- **Enter plain values**, not formulas. A formula in the sheet is rejected.

## Validation

The script stops with an error if:

| Check | Reason |
|---|---|
| No sheet named `Rules` | Wrong workbook |
| Headers not in row 1, or not matching one of the two templates | Template was modified |
| A value or header beyond the last filter column | Prevents silently ignored data |
| A row has a domain or filter but **no tag** | Incomplete rule |
| An **invalid `assetDomain`** (template with domain) | Must be one of the allowed values |
| The **same tag maps to two different domains** | A tag belongs to exactly one asset domain |
| A tag **without any filter** | It would match every device |
| A formula in a cell | Only literal values are supported |
| No complete rules at all | Empty sheet |

## Output

```json
{
  "rules": [
    {
      "tag": "SECAAS_WIN SRV",
      "assetDomain": "Hybrid cloud Windows",
      "computerDnsName": { "startsWith": "DC" },
      "osPlatform": { "startsWith": "Windows" }
    },
    {
      "tag": "SECAAS_WKS",
      "assetDomain": "Workplace",
      "osPlatform": { "startsWith": "Windows1" },
      "isAadJoined": { "equals": true }
    }
  ]
}
```

With the original template (no `assetDomain` column), the `assetDomain` property is left out.

## Using the output in a deployment

Put the generated object as the value of `taggingRules` in the customer parameter file (see [Deploying to a customer](../README.md#deploying-to-a-customer)):

```json
"taggingRules": {
    "value": { "rules": [ ... ] }
}
```

Or do it from PowerShell:

```powershell
$params = Get-Content .\customerX.azuredeploy.parameters.json -Raw | ConvertFrom-Json
$params.parameters.taggingRules.value = Get-Content .\customerX-rules.json -Raw | ConvertFrom-Json
$params | ConvertTo-Json -Depth 20 | Set-Content .\customerX.azuredeploy.parameters.json -Encoding utf8
```

> Workbooks, generated rule files and customer parameter files contain customer-specific names. Keep them out of public repositories.
