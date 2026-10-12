$ErrorActionPreference = "Stop"

$GitHubOwner = "jorgevales"
$GitHubRepository = "Copilot-Local-Agent"
$TokenFile = "$env:USERPROFILE\.github-vdi-bridge-token"
$BridgeLabel = "vdi-test"
$ProcessedLabel = "vdi-processed"

function Get-GitHubToken {
    if (-not (Test-Path $TokenFile)) {
        throw "GitHub token file not found: $TokenFile"
    }

    $encryptedToken = Get-Content $TokenFile -Raw
    $secureToken = $encryptedToken | ConvertTo-SecureString

    $credential = New-Object System.Management.Automation.PSCredential(
        "GitHub",
        $secureToken
    )

    return $credential.GetNetworkCredential().Password
}

function Invoke-GitHubRequest {
    param(
        [Parameter(Mandatory)]
        [ValidateSet("GET", "POST", "PATCH")]
        [string]$Method,

        [Parameter(Mandatory)]
        [string]$Uri,

        [object]$Body
    )

    $token = Get-GitHubToken

    $headers = @{
        Authorization          = "Bearer $token"
        Accept                 = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
        "User-Agent"           = "VDI-Test-Bridge"
    }

    $parameters = @{
        Method  = $Method
        Uri     = $Uri
        Headers = $headers
    }

    if ($null -ne $Body) {
        $parameters.ContentType = "application/json"
        $parameters.Body = $Body | ConvertTo-Json -Depth 10
    }

    return Invoke-RestMethod @parameters
}

function Add-IssueComment {
    param(
        [Parameter(Mandatory)]
        [int]$IssueNumber,

        [Parameter(Mandatory)]
        [string]$Comment
    )

    $uri = "https://api.github.com/repos/$GitHubOwner/$GitHubRepository/issues/$IssueNumber/comments"

    Invoke-GitHubRequest `
        -Method POST `
        -Uri $uri `
        -Body @{
            body = $Comment
        } | Out-Null
}

function Set-IssueProcessed {
    param(
        [Parameter(Mandatory)]
        [int]$IssueNumber,

        [object[]]$CurrentLabels = @()
    )

    $uri = "https://api.github.com/repos/$GitHubOwner/$GitHubRepository/issues/$IssueNumber"
    $updatedLabels = @(
        $CurrentLabels |
            ForEach-Object { $_.name } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Unique
    )

    if ($updatedLabels -notcontains $ProcessedLabel) {
        $updatedLabels += $ProcessedLabel
    }

    Invoke-GitHubRequest `
        -Method PATCH `
        -Uri $uri `
        -Body @{
            labels = $updatedLabels
            state = "closed"
        } | Out-Null
}

function Get-TestRequest {
    param(
        [Parameter(Mandatory)]
        [string]$IssueBody
    )

    try {
        $request = $IssueBody | ConvertFrom-Json
    }
    catch {
        throw "The issue body is not valid JSON."
    }

    if ([string]::IsNullOrWhiteSpace($request.request_id)) {
        throw "request_id is missing."
    }

    if ([string]::IsNullOrWhiteSpace($request.test_id)) {
        throw "test_id is missing."
    }

    return $request
}

function Invoke-ApprovedTest {
    param(
        [Parameter(Mandatory)]
        [object]$Request
    )

    switch ($Request.test_id) {
        "bridge_health" {
            return @{
                request_id = $Request.request_id
                test_id    = $Request.test_id
                status     = "PASS"
                bug_code   = $null
                summary    = "The VDI bridge successfully received and processed the request."
            }
        }

        default {
            return @{
                request_id = $Request.request_id
                test_id    = $Request.test_id
                status     = "BLOCKED"
                bug_code   = "TEST_NOT_APPROVED"
                summary    = "The test is not on the approved test list."
            }
        }
    }
}

$encodedBridgeLabel = [System.Uri]::EscapeDataString($BridgeLabel)

$issuesUri = "https://api.github.com/repos/$GitHubOwner/$GitHubRepository/issues?state=open&labels=$encodedBridgeLabel&per_page=20"

$issues = @(
    Invoke-GitHubRequest `
        -Method GET `
        -Uri $issuesUri
)

$requests = @(
    $issues | Where-Object {
        $labelNames = @($_.labels | ForEach-Object { $_.name })

        -not ($labelNames -contains $ProcessedLabel)
    }
)

if ($requests.Count -eq 0) {
    Write-Output "No pending VDI test requests."
    exit 0
}

foreach ($issue in $requests) {
    Write-Output "Processing GitHub issue #$($issue.number)"

    try {
        $request = Get-TestRequest -IssueBody $issue.body
        $result = Invoke-ApprovedTest -Request $request
    }
    catch {
        $result = @{
            request_id = "UNKNOWN"
            test_id    = "UNKNOWN"
            status     = "BLOCKED"
            bug_code   = "INVALID_REQUEST"
            summary    = $_.Exception.Message
        }
    }

    $resultJson = $result | ConvertTo-Json -Depth 5

    $comment = @"
VDI_TEST_RESULT

```json
$resultJson

```
"@
    Add-IssueComment `
        -IssueNumber $issue.number `
        -Comment $comment
    Set-IssueProcessed `
        -IssueNumber $issue.number `
        -CurrentLabels $issue.labels
    Write-Output "Issue #$($issue.number) completed with status $($result.status)."
}
