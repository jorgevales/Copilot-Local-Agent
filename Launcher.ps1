param([ValidateSet('Setup','Start','Tests')][string]$Mode = 'Start')
$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
$productionShare = ([System.IO.Path]::GetPathRoot($repoRoot) -ieq 'S:\')
$candidates = [System.Collections.Generic.List[string]]::new()
$seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

function Add-PythonCandidate([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return }
    $candidate = $Value.Trim().Trim('"')
    if ([System.IO.Path]::GetFileName($candidate) -ine 'python.exe') { return }
    if ($productionShare -and ([System.IO.Path]::GetPathRoot($candidate) -ine 'S:\')) { return }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { return }
    $entry = Get-Item -LiteralPath $candidate -Force
    if (($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return }
    $parent = $entry.Directory
    while ($parent) {
        if (($parent.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return }
        $parent = $parent.Parent
    }
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    if ($productionShare -and ([System.IO.Path]::GetPathRoot($resolved) -ine 'S:\')) { return }
    if ($seen.Add($resolved)) { $candidates.Add($resolved) }
}

function Get-OneDriveRoots {
    $roots = [System.Collections.Generic.List[string]]::new()
    $unique = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($name in @('OneDrive','OneDriveCommercial','OneDriveConsumer')) {
        $path = [Environment]::GetEnvironmentVariable($name)
        if ($path -and (Test-Path -LiteralPath $path -PathType Container) -and $unique.Add($path)) { $roots.Add($path) }
    }
    $accountKey = 'HKCU:\Software\Microsoft\OneDrive\Accounts'
    if (Test-Path -LiteralPath $accountKey) {
        foreach ($entry in @(Get-ChildItem -LiteralPath $accountKey -ErrorAction SilentlyContinue | Select-Object -First 32)) {
            $path = (Get-ItemProperty -LiteralPath $entry.PSPath -Name UserFolder -ErrorAction SilentlyContinue).UserFolder
            if ($path -and (Test-Path -LiteralPath $path -PathType Container) -and $unique.Add($path)) { $roots.Add($path) }
        }
    }
    return $roots.ToArray()
}

try {
    $savedInterpreters = [System.Collections.Generic.List[string]]::new()
    foreach ($account in @(Get-OneDriveRoots)) {
        $settingsPath = Join-Path $account 'Copilot Agent\settings.json'
        if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
            if ((Get-Item -LiteralPath $settingsPath).Length -le 65536) {
                try {
                    $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    if ($settings.selected_account -eq $true -and $settings.python_executable) { $savedInterpreters.Add([string]$settings.python_executable) }
                } catch { Write-Host 'A saved account setting could not be read; the application will ask for an account choice.' }
            }
        }
    }
    if ($env:COPILOT_PYTHON) {
        Add-PythonCandidate $env:COPILOT_PYTHON
        if ($candidates.Count -ne 1) { throw 'COPILOT_PYTHON must identify an existing Python executable on S: for a shared-drive deployment.' }
    } else {
        foreach ($value in $savedInterpreters) { Add-PythonCandidate $value }
        if ($candidates.Count -eq 0) {
            $operatorConfig = Join-Path $repoRoot 'python-launcher.txt'
            if (Test-Path -LiteralPath $operatorConfig -PathType Leaf) {
                Add-PythonCandidate ([string](Get-Content -LiteralPath $operatorConfig -Encoding UTF8 -TotalCount 1))
            }
        }
        if ($candidates.Count -eq 0 -and -not $productionShare) {
            Add-PythonCandidate (Join-Path $repoRoot '.venv\Scripts\python.exe')
        }
        if ($candidates.Count -eq 0) {
            foreach ($command in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) { Add-PythonCandidate $command.Source }
            $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
            if ($pythonLauncher) {
                foreach ($line in @(& $pythonLauncher.Source -0p 2>$null)) {
                    if ($line -match '([A-Za-z]:\\.+?python\.exe)\s*$') { Add-PythonCandidate $Matches[1] }
                }
            }
            $nearby = [System.Collections.Generic.List[string]]::new()
            $cursor = [System.IO.DirectoryInfo]::new($repoRoot)
            for ($depth = 0; $depth -lt 4 -and $cursor; $depth++) {
                if (-not $productionShare -or $cursor.Root.FullName -ieq 'S:\') {
                    $nearby.Add($cursor.FullName)
                    foreach ($folder in @('Python','python','Shared Python','.venv')) {
                        $nearby.Add((Join-Path $cursor.FullName $folder))
                    }
                }
                $cursor = $cursor.Parent
            }
            foreach ($directory in $nearby) {
                Add-PythonCandidate (Join-Path $directory 'python.exe')
                Add-PythonCandidate (Join-Path $directory 'Scripts\python.exe')
            }
        }
        if ($candidates.Count -eq 0 -and (Test-Path -LiteralPath 'S:\' -PathType Container)) {
            Write-Host 'Finding shared Python on S: (bounded directory search, no account or document scanning).'
            $queue = [System.Collections.Generic.Queue[object]]::new()
            $queue.Enqueue(@{ Path='S:\'; Depth=0 })
            $visited = 0
            while ($queue.Count -gt 0 -and $visited -lt 20000) {
                $item = $queue.Dequeue()
                $visited++
                Add-PythonCandidate (Join-Path $item.Path 'python.exe')
                if ($item.Depth -ge 8) { continue }
                foreach ($child in @(Get-ChildItem -LiteralPath $item.Path -Directory -Force -ErrorAction SilentlyContinue)) {
                    if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
                    if ($child.Name -in @('.git','node_modules','runtime','workspace','deliveries')) { continue }
                    if ($queue.Count -lt 20000) { $queue.Enqueue(@{ Path=$child.FullName; Depth=$item.Depth+1 }) }
                }
            }
        }
    }
    if ($candidates.Count -eq 0) { throw 'No shared Python was found within the bounded S: search. Ask the shared-Python operator to check installation/access; no private paths need to be supplied to chat.' }
    if ($candidates.Count -eq 1) {
        $python = $candidates[0]
    } else {
        Write-Host 'Available shared Python interpreters:'
        for ($index = 0; $index -lt $candidates.Count; $index++) { Write-Host (('{0}. {1}' -f ($index+1), $candidates[$index])) }
        $selected = 0
        for ($attempt = 0; $attempt -lt 5; $attempt++) {
            $answer = Read-Host 'Choose an interpreter number'
            if ([int]::TryParse($answer, [ref]$selected) -and $selected -ge 1 -and $selected -le $candidates.Count) { break }
            $selected = 0
        }
        if ($selected -eq 0) { throw 'Interpreter selection stopped after five attempts.' }
        $python = $candidates[$selected-1]
    }
    Write-Host ('Using Python: ' + $python)
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $pythonProbe = @'
import ntpath
import sys
import sysconfig
from importlib.metadata import distribution

def assert_shared_runtime(executable, base_prefix, base_executable, stdlib):
    paths = {'running executable': executable, 'base Python prefix': base_prefix,
             'base executable': base_executable or executable, 'standard library': stdlib}
    for label, value in paths.items():
        if not isinstance(value, str) or not ntpath.isabs(value) or ntpath.splitdrive(value)[0].upper() != 'S:':
            raise RuntimeError('Shared deployment requires the '+label+' on S:. This interpreter depends on a local or unmapped Python runtime; the operator must provide a complete shared installation.')

def locked_versions(text):
    if len(text) > 65536:
        raise RuntimeError('Shared dependency lock exceeds its size limit.')
    result = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, pinned = line.partition('==')
        if (not separator or not name or not pinned or name in result
                or not all(char.isalnum() or char in '._-' for char in name)
                or not all(char.isalnum() or char in '._+-!' for char in pinned)):
            raise RuntimeError('Shared dependency lock must contain unique exact package versions.')
        result[name] = pinned
    if not {'playwright', 'greenlet', 'pyee', 'typing_extensions'}.issubset(result):
        raise RuntimeError('Shared dependency lock must include Playwright and its required dependencies.')
    return result

def assert_dependencies(installed, expected, require_shared):
    for name, pinned in expected.items():
        record = installed.get(name, {})
        if record.get('version') != pinned:
            raise RuntimeError('Required dependency '+name+'=='+pinned+' is unavailable. The operator must install requirements.lock.txt for this shared interpreter.')
        location = record.get('location')
        if require_shared and (not isinstance(location, str) or not ntpath.isabs(location)
                               or ntpath.splitdrive(location)[0].upper() != 'S:'):
            raise RuntimeError('Shared dependency '+name+' must be installed on S:, not in a local or per-user package directory.')

assert sys.version_info >= (3, 10), 'Python 3.10+ is required'
shared = sys.argv[1] == 'shared'
if shared:
    assert_shared_runtime(sys.executable, sys.base_prefix,
                          getattr(sys, '_base_executable', None), sysconfig.get_path('stdlib'))
    with open(sys.argv[2], encoding='utf-8-sig') as stream:
        expected = locked_versions(stream.read(65537))
else:
    expected = {'playwright':'1.55.0'}
installed = {}
for name in expected:
    package = distribution(name)
    installed[name] = {'version':package.version, 'location':str(package.locate_file(''))}
assert_dependencies(installed, expected, shared)
print('Python runtime and Playwright verified.')
'@
    $runtimeMode = if ($productionShare) { 'shared' } else { 'development' }
    $pythonArgs = if ($productionShare) { @('-B','-E','-s') } else { @('-B') }
    & $python @pythonArgs -c $pythonProbe $runtimeMode (Join-Path $repoRoot 'requirements.lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Shared dependencies are unavailable. The operator must install the approved requirements once; this launcher does not create a virtual environment or install packages.' }
    Push-Location -LiteralPath $repoRoot
    try {
        if ($Mode -eq 'Setup') {
            & $python @pythonArgs (Join-Path $repoRoot 'app.py') --setup-only
        } elseif ($Mode -eq 'Start') {
            & $python @pythonArgs (Join-Path $repoRoot 'app.py')
        } else {
            & $python @pythonArgs (Join-Path $repoRoot 'app.py') --setup-only
            if ($LASTEXITCODE -ne 0) { throw 'Personal storage setup must complete before running tests.' }
            $stores = [System.Collections.Generic.List[string]]::new()
            foreach ($account in @(Get-OneDriveRoots)) {
                $directory = Join-Path $account 'Copilot Agent'
                $settingsPath = Join-Path $directory 'settings.json'
                if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
                    $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    if ($settings.selected_account -eq $true) { $stores.Add($directory) }
                }
            }
            if ($stores.Count -ne 1) { throw 'A single selected OneDrive account is required for per-user test storage.' }
            $env:COPILOT_TEST_ROOT = Join-Path $stores[0] 'runtime\test-runs'
            New-Item -ItemType Directory -Path $env:COPILOT_TEST_ROOT -Force | Out-Null
            $env:TEMP = $env:COPILOT_TEST_ROOT
            $env:TMP = $env:COPILOT_TEST_ROOT
            & $python @pythonArgs -m unittest discover -s tests -v
        }
        $result = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    exit $result
} catch {
    Write-Host ('Setup/run stopped: ' + $_.Exception.Message)
    exit 1
}
