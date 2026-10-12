$ErrorActionPreference = "Stop"

$GitHubOwner = "jorgevales"
$GitHubRepository = "Copilot-Local-Agent"
$BridgeLabel = "vdi-test"
$ProcessedLabel = "vdi-processed"

$script:GitHubToken = $null
$secureToken = $null
$credential = $null
$rawToken = $null

function Invoke-GitHubRequest {
    param(
        [Parameter(Mandatory)]
        [ValidateSet("GET", "POST", "PATCH")]
        [string]$Method,

        [Parameter(Mandatory)]
        [string]$Uri,

        [object]$Body
    )

    if (-not $script:GitHubToken) {
        throw "The GitHub token has not been initialized."
    }

    $headers = @{
        Authorization         = "Bearer $script:GitHubToken"
        Accept                = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
    }

    foreach ($name in $headers.Keys) {
        $headerValue = $headers[$name]

        if ($headerValue -match '[\p{Cc}\p{Cf}]') {
            throw "Header '$name' contains an invalid hidden character."
        }
    }

    $parameters = @{
        Method      = $Method
        Uri         = $Uri
        Headers     = $headers
        UserAgent   = "VDI-Test-Bridge"
        ErrorAction = "Stop"
    }

    if ($null -ne $Body) {
        $parameters.ContentType = "application/json; charset=utf-8"
        $json = $Body | ConvertTo-Json -Depth 10
        $encoding = New-Object System.Text.UTF8Encoding
        $parameters.Body = $encoding.GetBytes($json)
    }

    # Do not automatically retry requests that write to GitHub.
    Invoke-RestMethod @parameters
}

function Add-IssueComment {
    param(
        [Parameter(Mandatory)]
        [int]$IssueNumber,

        [Parameter(Mandatory)]
        [string]$Comment
    )

    $uri = "https://api.github.com/repos/$GitHubOwner/$GitHubRepository/issues/$IssueNumber/comments"

    Invoke-GitHubRequest -Method "POST" -Uri $uri -Body @{
        body = $Comment
    } | Out-Null
}

function Set-IssueProcessed {
    param(
        [Parameter(Mandatory)]
        [int]$IssueNumber
    )

    $uri = "https://api.github.com/repos/$GitHubOwner/$GitHubRepository/issues/$IssueNumber"

    # Preserve existing labels.
    $currentIssue = Invoke-GitHubRequest -Method "GET" -Uri $uri

    $labels = @(
        $currentIssue.labels | ForEach-Object { $_.name }
        $BridgeLabel
        $ProcessedLabel
    ) | Select-Object -Unique

    Invoke-GitHubRequest -Method "PATCH" -Uri $uri -Body @{
        labels = @($labels)
        state  = "closed"
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
                summary    = "The requested test ID is not on the approved test list."
            }
        }
    }
}

try {
    $secureToken = Read-Host "Paste your GitHub token" -AsSecureString

    $credential = New-Object System.Management.Automation.PSCredential(
        "GitHub",
        $secureToken
    )

    $rawToken = $credential.GetNetworkCredential().Password

    # Remove whitespace, control characters and invisible format characters.
    $script:GitHubToken = $rawToken -replace '[\s\p{Cc}\p{Cf}]', ''
    $rawToken = $null

    if (-not $script:GitHubToken) {
        throw "No GitHub token was entered."
    }

    if ($script:GitHubToken -notmatch '\A[A-Za-z0-9_]+\z') {
        throw "The token contains unexpected characters. Paste only the token, without quotes or surrounding text."
    }

    # The configured label uses only URL-safe letters and a hyphen.
    if ($BridgeLabel -notmatch '\A[A-Za-z0-9_-]+\z') {
        throw "The bridge label must contain only letters, numbers, underscores or hyphens."
    }

    $issuesUri = "https://api.github.com/repos/$GitHubOwner/$GitHubRepository/issues?state=open&labels=$BridgeLabel&per_page=20"

    $issues = @(Invoke-GitHubRequest -Method "GET" -Uri $issuesUri)

    $requests = @(
        $issues | Where-Object {
            $labelNames = @(
                $_.labels | ForEach-Object { $_.name }
            )

            (-not $_.pull_request) -and
            (-not ($labelNames -contains $ProcessedLabel))
        }
    )

    if ($requests.Count -eq 0) {
        Write-Output "No pending VDI test requests."
    }
    else {
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
            $comment = "VDI_TEST_RESULT`r`n`r`n$resultJson"

            Add-IssueComment `
                -IssueNumber $issue.number `
                -Comment $comment

            Set-IssueProcessed -IssueNumber $issue.number

            Write-Output "Issue #$($issue.number) completed with status $($result.status)."
        }
    }
}
finally {
    $script:GitHubToken = $null
    $rawToken = $null
    $credential = $null

    if ($null -ne $secureToken) {
        $secureToken.Dispose()
        $secureToken = $null
    }
}
