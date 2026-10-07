param([ValidateSet('Setup','Start','Tests')][string]$Mode = 'Start')
$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
$productionShare = ([System.IO.Path]::GetPathRoot($repoRoot) -ieq 'S:\')
$candidates = [System.Collections.Generic.List[string]]::new()
$seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

function Add-PythonCandidate([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return }
    $candidate = $Value.Trim().Trim('"').Trim("'")
    if ($candidate -notmatch '^(?:[A-Za-z]:\\|\\\\[^\\]+\\[^\\]+\\)') { return }
    if (Test-Path -LiteralPath $candidate -PathType Container) {
        Add-PythonCandidate (Join-Path $candidate 'python.exe')
        Add-PythonCandidate (Join-Path $candidate 'Scripts\python.exe')
        return
    }
    if ([System.IO.Path]::GetFileName($candidate) -ine 'python.exe') { return }
    if ($productionShare -and ([System.IO.Path]::GetPathRoot($candidate) -ine 'S:\')) { return }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { return }
    $entry = Get-Item -LiteralPath $candidate -Force
    if (-not (Test-SafePythonEntry $entry)) { return }
    $parent = $entry.Directory
    while ($parent) {
        if (-not (Test-SafePythonEntry $parent)) { return }
        $parent = $parent.Parent
    }
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    if ($productionShare -and ([System.IO.Path]::GetPathRoot($resolved) -ine 'S:\')) { return }
    if ($seen.Add($resolved)) { $candidates.Add($resolved) }
}

function Test-AllowedCloudTag([uint64]$Tag) {
    return (-not $productionShare -and ($Tag -band 4294905855) -eq 2415919130 -and ($Tag -band 536870912) -eq 0)
}

function Test-SafePythonEntry($Entry) {
    if (($Entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) { return $true }
    if ($productionShare) { return $false }
    if (-not ('CopilotLauncher.ReparseMetadata' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
namespace CopilotLauncher {
 public static class ReparseMetadata {
  [StructLayout(LayoutKind.Sequential)] private struct TagInfo { public uint Attributes; public uint Tag; }
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] private static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
  [DllImport("kernel32.dll", SetLastError=true)] private static extern bool GetFileInformationByHandleEx(SafeFileHandle handle, int infoClass, out TagInfo info, uint size);
  public static uint ReadTag(string path) {
   using (var handle = CreateFileW(path,0,7,IntPtr.Zero,3,0x02200000,IntPtr.Zero)) {
    if (handle.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
    TagInfo info;
    if (!GetFileInformationByHandleEx(handle,9,out info,8)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
    return info.Tag;
   }
  }
 }
}
'@
    }
    try { return (Test-AllowedCloudTag ([CopilotLauncher.ReparseMetadata]::ReadTag($Entry.FullName))) } catch { return $false }
}

function Read-PythonMethod {
    Write-Host 'Python setup: 1. Detect automatically  2. Paste an installation folder or python.exe path'
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        $answer = (Read-Host 'Choose 1 or 2').Trim()
        if ($answer -in @('1','2')) { return $answer }
        Write-Host 'Enter 1 for automatic detection or 2 to paste a path.'
    }
    throw 'Python setup selection stopped after five attempts.'
}

function Read-PythonPath {
    Write-Host 'Paste the full path to python.exe or its installation folder. Surrounding quotes are allowed.'
    if ($productionShare) { Write-Host 'The complete Python installation must be on S:.' }
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        Add-PythonCandidate (Read-Host 'Python path')
        if ($candidates.Count -gt 0) { return }
        Write-Host 'No usable python.exe was found at that absolute path. Check the folder and access permissions.'
    }
    throw 'Python path entry stopped after five attempts.'
}

function Invoke-SetupPython([string]$Executable, [string[]]$Arguments) {
    # Windows PowerShell 5 turns native stderr into a terminating error when
    # ErrorActionPreference is Stop. Let Python print its complete diagnostic.
    $ErrorActionPreference = 'Continue'
    & $Executable @Arguments | Out-Host
    $commandExitCode = $LASTEXITCODE
    if ($commandExitCode -ne 0) { throw ('Python setup command failed with exit code ' + $commandExitCode + '. See the complete Python error above. Existing files were retained.') }
}

function Get-PipConfiguration([string]$Executable, [string[]]$PythonFlags) {
    $ErrorActionPreference = 'Continue'
    $configuration = @(& $Executable @PythonFlags -m pip config list)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to verify pip installation settings. Existing files were retained.' }
    return ($configuration -join "`n")
}

function Get-WorkingPip([string]$Executable, [string[]]$PythonFlags) {
    $ErrorActionPreference = 'Continue'
    $description = @(& $Executable @PythonFlags -m pip --version 2>$null)
    if ($LASTEXITCODE -ne 0 -or $description.Count -eq 0) { return $null }
    # A damaged virtualenv seed can import pip but lack its distribution metadata.
    & $Executable @PythonFlags -c 'import pip; from importlib.metadata import distribution; assert distribution(pip.__name__).version == pip.__version__' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($description -join ' ').Trim()
}

function Get-RecoveryBasePython([string]$SelectedPython, [string[]]$PythonFlags, [string]$EnvironmentPython) {
    if ([System.IO.Path]::GetFullPath($SelectedPython) -ine [System.IO.Path]::GetFullPath($EnvironmentPython)) { return $SelectedPython }
    $ErrorActionPreference = 'Continue'
    $locator = @'
import sys
print(getattr(sys, '_base_executable', ''))
print(sys.base_prefix)
'@
    $reported = @(& $SelectedPython @PythonFlags -c $locator 2>$null)
    if ($LASTEXITCODE -ne 0 -or $reported.Count -lt 2) { throw 'The selected project environment cannot report its base Python installation. Existing files were retained.' }
    $possible = @([string]$reported[0], (Join-Path ([string]$reported[1]) 'python.exe'))
    foreach ($candidate in $possible) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            Write-Host ('Using the project environment''s reported base Python: ' + $candidate)
            return $candidate
        }
    }
    throw 'The selected project environment has no accessible base Python executable. Existing files were retained.'
}

function Preserve-ProjectEnvironment([string]$ProjectRoot, [string]$EnvironmentPath) {
    $entry = Get-Item -LiteralPath $EnvironmentPath -Force
    if (-not (Test-SafePythonEntry $entry)) { throw 'The project .venv must be a real directory, not a redirected path.' }
    $archivePath = Join-Path $ProjectRoot ('.venv-incomplete-' + [guid]::NewGuid().ToString('N'))
    $projectFull = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') + '\'
    if (-not ([System.IO.Path]::GetFullPath($EnvironmentPath).StartsWith($projectFull, [System.StringComparison]::OrdinalIgnoreCase) -and [System.IO.Path]::GetFullPath($archivePath).StartsWith($projectFull, [System.StringComparison]::OrdinalIgnoreCase))) { throw 'Environment recovery paths are outside the project.' }
    Move-Item -LiteralPath $EnvironmentPath -Destination $archivePath -ErrorAction Stop
    Write-Host ('Preserved the previous environment at ' + $archivePath)
}

function Initialize-AgentEnvironment([string]$BasePython, [string[]]$PythonFlags, [string]$Probe, [string]$RuntimeMode, [string]$ProjectRoot) {
    $environmentPath = Join-Path $ProjectRoot '.venv'
    $environmentPython = Join-Path $environmentPath 'Scripts\python.exe'
    $requirements = Join-Path $ProjectRoot 'requirements.lock.txt'
    $bootstrap = Join-Path $ProjectRoot 'bootstrap\virtualenv.pyz'
    $bootstrapSha256 = '9096EFA6E3A8457CC3EC56E749A2D1E17505B756EE3CB2B7E889526367EFC187'
    $setupLock = $null
    try {
        $lockPath = Join-Path $ProjectRoot '.venv-setup.lock'
        if (Test-Path -LiteralPath $lockPath) {
            if (-not (Test-SafePythonEntry (Get-Item -LiteralPath $lockPath -Force))) { throw 'Setup lock must not be a redirected path.' }
        }
        try {
            $setupLock = [System.IO.File]::Open((Join-Path $ProjectRoot '.venv-setup.lock'), [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        } catch { throw 'Another setup is running, or this project is not writable. Retry after setup completes.' }
        $BasePython = Get-RecoveryBasePython $BasePython $PythonFlags $environmentPython
        Invoke-SetupPython $BasePython ($PythonFlags + @('-c',$Probe,($RuntimeMode + '-bootstrap'),$requirements))
        if (Test-Path -LiteralPath $environmentPath) {
            $environmentEntry = Get-Item -LiteralPath $environmentPath -Force
            if (-not (Test-SafePythonEntry $environmentEntry)) { throw 'The project .venv must be a real directory, not a redirected path.' }
            $recoveryReason = $null
            if (-not (Test-Path -LiteralPath (Join-Path $environmentPath 'pyvenv.cfg') -PathType Leaf) -or -not (Test-Path -LiteralPath $environmentPython -PathType Leaf)) {
                $recoveryReason = 'The existing project Python environment is incomplete.'
            } elseif (-not (Get-WorkingPip $environmentPython $PythonFlags)) {
                $recoveryReason = 'The existing project Python environment has no working pip.'
            }
            if ($recoveryReason) {
                Write-Host $recoveryReason
                $basePip = Get-WorkingPip $BasePython $PythonFlags
                if ($basePip) { Write-Host ('Located pip in the selected Python installation: ' + $basePip) }
                else { Write-Host 'The selected Python has no working pip; the bundled bootstrap will seed it in the project environment.' }
                Preserve-ProjectEnvironment $ProjectRoot $environmentPath
            } else {
                Write-Host 'Reusing the existing project Python environment.'
            }
        }
        if (-not (Test-Path -LiteralPath $environmentPath)) {
            Write-Host 'Creating the project Python environment.'
            if (-not (Test-Path -LiteralPath $bootstrap -PathType Leaf) -or -not (Test-SafePythonEntry (Get-Item -LiteralPath $bootstrap -Force))) { throw 'Bundled virtualenv bootstrap is missing or redirected. Restore the official repository files and retry Setup.' }
            if ((Get-FileHash -LiteralPath $bootstrap -Algorithm SHA256).Hash -ne $bootstrapSha256) { throw 'Bundled virtualenv bootstrap failed its SHA-256 check. Restore the official repository files and retry Setup.' }
            try {
                Invoke-SetupPython $BasePython ($PythonFlags + @($bootstrap,'--no-download','--no-periodic-update',$environmentPath))
                if (-not (Get-WorkingPip $environmentPython $PythonFlags)) { throw 'Default virtualenv seeder did not create a working pip installation.' }
            } catch {
                Write-Host 'Default virtualenv seeder failed. Retrying with the direct pip seeder.'
                if (Test-Path -LiteralPath $environmentPath) { Preserve-ProjectEnvironment $ProjectRoot $environmentPath }
                Invoke-SetupPython $BasePython ($PythonFlags + @($bootstrap,'--no-download','--no-periodic-update','--seeder','pip',$environmentPath))
            }
        }
        if (-not (Test-Path -LiteralPath (Join-Path $environmentPath 'pyvenv.cfg') -PathType Leaf) -or -not (Test-Path -LiteralPath $environmentPython -PathType Leaf)) { throw 'Virtual environment creation was incomplete. Files were retained.' }
        $priorCandidates = $candidates
        $priorSeen = $seen
        try {
            $candidates = [System.Collections.Generic.List[string]]::new()
            $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
            Add-PythonCandidate $environmentPython
            if ($candidates.Count -ne 1) { throw 'Project environment Python is redirected or unavailable.' }
        } finally { $candidates = $priorCandidates; $seen = $priorSeen }
        Invoke-SetupPython $environmentPython ($PythonFlags + @('-c',$Probe,($RuntimeMode + '-bootstrap'),$requirements,$environmentPath))
        if (-not (Get-WorkingPip $environmentPython $PythonFlags)) { throw 'Project environment pip is unavailable after creation or reuse. Packages were not installed; existing files were retained.' }
        Write-Host 'Project environment pip verified.'
        if ($env:PIP_TARGET) { throw 'PIP_TARGET redirects package installation. Clear that override before running Setup; no settings were changed.' }
        $pipConfiguration = Get-PipConfiguration $environmentPython $PythonFlags
        if ($pipConfiguration -match '(?im)^\s*[^=]*\.target\s*=') { throw 'Pip configuration redirects installation with target. Remove that override before Setup; no settings were changed.' }
        Write-Host 'Installing the pinned project dependencies (the configured package mirror is respected).'
        Invoke-SetupPython $environmentPython ($PythonFlags + @('-m','pip','install','--requirement',$requirements,'--disable-pip-version-check','--no-user','--prefix',$environmentPath))
        return $environmentPython
    } finally { if ($setupLock) { $setupLock.Dispose() } }
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
    $projectVersion = $null
    if ($Mode -eq 'Start') {
        Write-Host 'Which version do you want to run? 1. Live repository  2. Copilot testing environment'
        $projectVersion = (Read-Host 'Choose 1 or 2').Trim()
        if ($projectVersion -notin @('1','2')) { throw 'Enter 1 or 2; no version was started.' }
    }
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
        if ($Mode -ne 'Setup') {
            Add-PythonCandidate (Join-Path $repoRoot '.venv\Scripts\python.exe')
            if ($candidates.Count -eq 0) { foreach ($value in $savedInterpreters) { Add-PythonCandidate $value } }
            if ($candidates.Count -eq 0) {
                $operatorConfig = Join-Path $repoRoot 'python-launcher.txt'
                if (Test-Path -LiteralPath $operatorConfig -PathType Leaf) {
                    Add-PythonCandidate ([string](Get-Content -LiteralPath $operatorConfig -Encoding UTF8 -TotalCount 1))
                }
            }
        }
        $method = if ($candidates.Count -eq 0) { Read-PythonMethod } else { 'saved' }
        if ($method -eq '2') { Read-PythonPath }
        if ($method -eq '1') {
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
            if ($candidates.Count -eq 0) {
                Write-Host 'Automatic detection found no usable Python. Paste its path to continue.'
                Read-PythonPath
            }
        }
    }
    if ($candidates.Count -eq 0) { throw 'No usable Python interpreter was selected.' }
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
import os
import sys
import sysconfig
from functools import lru_cache
from importlib.metadata import distribution

WINDOWS_SLASH = chr(92)

def normalized_final_path(value):
    result = os.path.realpath(value, strict=True)
    extended = WINDOWS_SLASH * 2 + '?' + WINDOWS_SLASH
    unc_prefix = extended + 'UNC' + WINDOWS_SLASH
    if result[:len(unc_prefix)].casefold() == unc_prefix.casefold():
        result = WINDOWS_SLASH * 2 + result[len(unc_prefix):]
    elif result.startswith(extended):
        result = result[len(extended):]
    return ntpath.normcase(ntpath.normpath(result)).rstrip(WINDOWS_SLASH)

@lru_cache(maxsize=1)
def mapped_shared_root():
    try:
        result = normalized_final_path('S:' + WINDOWS_SLASH)
    except (OSError, ValueError):
        return None
    return result if result.startswith(WINDOWS_SLASH * 2) else None

def is_shared_path(value):
    if not isinstance(value, str) or not ntpath.isabs(value):
        return False
    if ntpath.splitdrive(ntpath.normpath(value))[0].casefold() == 's:':
        return True
    if not value.startswith(WINDOWS_SLASH * 2):
        return False
    root = mapped_shared_root()
    if root is None:
        return False
    try:
        resolved = normalized_final_path(value)
    except (OSError, ValueError):
        return False
    return resolved == root or resolved.startswith(root + WINDOWS_SLASH)

def same_directory(left, right):
    identity_match = None
    try:
        identity_match = os.path.samefile(left, right)
    except (OSError, ValueError):
        pass
    if identity_match:
        return True
    try:
        return normalized_final_path(left) == normalized_final_path(right)
    except (OSError, ValueError):
        return identity_match

def valid_environment_prefix(actual, base, expected):
    return same_directory(actual, expected) is True and same_directory(actual, base) is False

def assert_shared_runtime(executable, base_prefix, base_executable, stdlib):
    paths = {'running executable': executable, 'base Python prefix': base_prefix,
             'base executable': base_executable or executable, 'standard library': stdlib}
    for label, value in paths.items():
        if not is_shared_path(value):
            raise RuntimeError('Shared deployment requires the '+label+' on S: or its mapped UNC share. Reported runtime paths: '+repr(paths)+'. This interpreter depends on a local or unmapped Python runtime; the operator must provide a complete shared installation.')

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
        if require_shared and not is_shared_path(location):
            raise RuntimeError('Shared dependency '+name+' must be installed on S: or its mapped UNC share, not in a local or per-user package directory. Reported location: '+repr(location))

assert sys.version_info >= (3, 10), 'Python 3.10+ is required'
if len(sys.argv) > 3:
    if not valid_environment_prefix(sys.prefix, sys.base_prefix, sys.argv[3]):
        raise RuntimeError('Existing project environment is not a valid virtual environment at the expected path. Files were retained.')
bootstrap = sys.argv[1].endswith('-bootstrap')
shared = sys.argv[1].startswith('shared')
if shared:
    assert_shared_runtime(sys.executable, sys.base_prefix,
                          getattr(sys, '_base_executable', None), sysconfig.get_path('stdlib'))
if bootstrap:
    print('Base Python runtime verified.')
    sys.exit(0)
if shared:
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
    [string[]]$pythonArgs = if ($productionShare) { @('-B','-E','-s') } else { @('-B') }
    if ($Mode -eq 'Setup') { $python = Initialize-AgentEnvironment $python $pythonArgs $pythonProbe $runtimeMode $repoRoot }
    & $python @pythonArgs -c $pythonProbe $runtimeMode (Join-Path $repoRoot 'requirements.lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python or pinned dependencies are unavailable. Run Setup.cmd to create or repair the project environment; existing files are retained.' }
    Push-Location -LiteralPath $repoRoot
    try {
        if ($Mode -eq 'Setup') {
            & $python @pythonArgs (Join-Path $repoRoot 'app.py') --setup-only
        } elseif ($Mode -eq 'Start') {
            & $python @pythonArgs (Join-Path $repoRoot 'version_launcher.py') $projectVersion
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
