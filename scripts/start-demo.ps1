<#
.SYNOPSIS
    Starts the SRFU website and the scraper worker for the Windows local demo.

.DESCRIPTION
    Uses the project's virtual environment, checks that the setup is complete,
    starts the website and the background worker as two separate processes,
    and confirms both are healthy. It never starts a second copy of a process
    that is already running, and it never starts a scrape: the worker only
    processes jobs that an Admin has queued on the Scraper page.

    It does not run migrations and never changes data. If the database needs
    migrating it stops and says so.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1 -Status
    powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1 -Stop

.PARAMETER Stop
    Stop the website and worker started for this project folder.
.PARAMETER Status
    Report what is running and exit.
.PARAMETER Port
    Website port (default 8000).
.PARAMETER VenvPath
    Virtual environment folder. Default: .venv, then venv, whichever has the
    required packages installed.
.PARAMETER SettingsModule
    Django settings module for both processes (testing with another database).
.PARAMETER ExtraPythonPath
    Extra folder added to PYTHONPATH (used with -SettingsModule).
.PARAMETER OpenBrowser
    Open the login page in the default browser once everything is running.
.PARAMETER StartupTimeoutSeconds
    How long to wait for the website and worker to report healthy (default 45).
#>
[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$Status,
    [int]$Port = 8000,
    [string]$VenvPath = '',
    [string]$SettingsModule = '',
    [string]$ExtraPythonPath = '',
    [int]$StartupTimeoutSeconds = 45,
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Manage = Join-Path $Root 'manage.py'
$LogDir = Join-Path $Root 'logs'
$LoginUrl = "http://127.0.0.1:$Port/accounts/login/"

function Fail([string]$Message, [string[]]$Hints = @()) {
    Write-Host "FAILED: $Message" -ForegroundColor Red
    foreach ($h in $Hints) { Write-Host "  $h" -ForegroundColor Yellow }
    exit 1
}

function Ok([string]$Message) { Write-Host "OK: $Message" -ForegroundColor Green }
function Info([string]$Message) { Write-Host $Message }

function Show-LogTail([string]$Path, [int]$Lines = 12) {
    if (Test-Path $Path) {
        $tail = Get-Content $Path -Tail $Lines -ErrorAction SilentlyContinue
        if ($tail) {
            Write-Host "  Last lines of ${Path}:" -ForegroundColor Yellow
            $tail | ForEach-Object { Write-Host "    $_" }
        }
    }
}

if (-not (Test-Path $Manage)) {
    Fail "manage.py was not found next to the scripts folder ($Root)." @('Run this script from inside the project folder.')
}

# ------------------------------------------------------------ venv candidates
$candidates = @()
if ($VenvPath) {
    $candidates += $VenvPath
} else {
    $candidates += (Join-Path $Root '.venv'), (Join-Path $Root 'venv')
}
# Interpreters from any of this project's virtual environments identify its processes.
$projectVenvDirs = @((Join-Path $Root '.venv'), (Join-Path $Root 'venv')) + $candidates | Select-Object -Unique

# ---------------------------------------------------------------- processes
function Test-Contains([string]$Text, [string]$Part) {
    return $Text -and $Text.IndexOf($Part, [StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Test-InProjectVenv([string]$ExePath) {
    if (-not $ExePath) { return $false }
    foreach ($dir in $projectVenvDirs) {
        if (Test-Contains $ExePath ($dir.TrimEnd('\') + '\')) { return $true }
    }
    return $false
}

function Get-ProjectProcesses([string]$Command) {
    # A process belongs to this project when it runs `manage.py <Command>` and either
    #   - was started with this project's full manage.py path (this launcher), or
    #   - uses an interpreter from this project's virtual environment (started by hand
    #     from the project folder, for example `python manage.py runserver`).
    # Interpreter children of a launcher (the venv shim and the dev-server reloader)
    # that run the same command are included, so Stop leaves nothing behind.
    $all = @(Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and (Test-Contains $_.CommandLine 'manage.py') -and (Test-Contains $_.CommandLine $Command) })

    $hits = @($all | Where-Object {
        (Test-Contains $_.CommandLine $Manage) -or (Test-InProjectVenv $_.ExecutablePath)
    })

    do {
        $added = $false
        foreach ($p in $all) {
            if (($hits.ProcessId -notcontains $p.ProcessId) -and ($hits.ProcessId -contains $p.ParentProcessId)) {
                $hits += $p
                $added = $true
            }
        }
    } while ($added)

    return $hits
}

function Get-PortOwner([int]$LocalPort) {
    $conn = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { return $conn.OwningProcess }
    return $null
}

function Stop-ProjectProcesses([string]$Command) {
    $procs = @(Get-ProjectProcesses $Command)
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    return $procs.Count
}

if ($Status -or $Stop) {
    $web = @(Get-ProjectProcesses 'runserver')
    $worker = @(Get-ProjectProcesses 'run_intake_worker')

    if ($Status) {
        $webText = if ($web.Count) { 'running (PID ' + (($web | ForEach-Object ProcessId) -join ', ') + ')' } else { 'not running' }
        $workerText = if ($worker.Count) { 'running (PID ' + (($worker | ForEach-Object ProcessId) -join ', ') + ')' } else { 'not running' }
        Info "Website: $webText"
        Info "Worker:  $workerText"
        $owner = Get-PortOwner $Port
        if ($owner -and -not ($web | Where-Object { $_.ProcessId -eq $owner })) {
            Write-Host "Note: port $Port is in use by another program (PID $owner)." -ForegroundColor Yellow
        }
        exit 0
    }

    if ($worker.Count) {
        Info 'Stopping the worker. A scrape that is mid-run is re-queued automatically after its 5 minute lease and resumes without creating duplicates.'
    }
    $w = Stop-ProjectProcesses 'run_intake_worker'
    $s = Stop-ProjectProcesses 'runserver'
    Ok "Stopped $s website process(es) and $w worker process(es)."
    exit 0
}

# ------------------------------------------------------------ find the venv
$Python = $null
$venvNotes = @()

foreach ($dir in $candidates) {
    $exe = Join-Path $dir 'Scripts\python.exe'
    if (-not (Test-Path $exe)) { $venvNotes += "$dir : no Scripts\python.exe"; continue }

    & $exe -c 'import django, openai, bs4, openpyxl, dotenv, requests, pydantic' 2>$null
    if ($LASTEXITCODE -eq 0) { $Python = $exe; break }
    $venvNotes += "$dir : required packages are not installed"
}

if (-not $Python) {
    Fail 'No usable virtual environment was found.' (@($venvNotes) + @(
        'Create one and install the packages (README, Setup step 1):',
        '  py -3.12 -m venv .venv',
        '  .venv\Scripts\python.exe -m pip install -r requirements.txt'))
}
Ok "Using $Python"

# ---------------------------------------------------- environment variables
function Get-EnvFileValue([string]$Name) {
    $envFile = Join-Path $Root '.env'
    if (-not (Test-Path $envFile)) { return $null }
    foreach ($line in Get-Content $envFile) {
        if ($line -match "^\s*$Name\s*=\s*(.*)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}

$missing = @()
foreach ($name in 'DJANGO_SECRET_KEY', 'OPENAI_API_KEY') {
    $fromProcess = [Environment]::GetEnvironmentVariable($name)
    $fromFile = Get-EnvFileValue $name
    if (-not $fromProcess -and -not $fromFile) { $missing += $name }
}
if ($missing.Count) {
    $verb = if ($missing.Count -gt 1) { 'are' } else { 'is' }
    Fail ("Setup is incomplete: " + ($missing -join ' and ') + " $verb not set.") @(
        'Copy .env.example to .env and fill it in (README, Setup step 2).')
}

# Environment for both child processes.
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
if ($SettingsModule) { $env:DJANGO_SETTINGS_MODULE = $SettingsModule }
if ($ExtraPythonPath) {
    $env:PYTHONPATH = if ($env:PYTHONPATH) { "$ExtraPythonPath;$env:PYTHONPATH" } else { $ExtraPythonPath }
}

# ------------------------------------------------------ project health checks
function Invoke-Manage([string[]]$Arguments) {
    # Windows PowerShell 5.1 turns native stderr into terminating errors when
    # ErrorActionPreference is Stop, so relax it for the call only.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Python $Manage @Arguments 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return @{ Code = $code; Output = $out }
}

$check = Invoke-Manage @('check')
if ($check.Code -ne 0) {
    Fail 'The project configuration check failed.' (($check.Output -split "`r?`n" | Select-Object -Last 8))
}
Ok 'Configuration check passed'

$migrations = Invoke-Manage @('migrate', '--check')
if ($migrations.Code -ne 0) {
    Fail 'The database has changes that have not been applied (or cannot be read).' @(
        'Back up db.sqlite3 first, then run:  python manage.py migrate',
        'This launcher never changes the database structure itself.')
}
Ok 'Database is up to date'

# --------------------------------------------------------- duplicate checks
New-Item -ItemType Directory -Force $LogDir | Out-Null

$startedProcs = @()
$webRunning = @(Get-ProjectProcesses 'runserver')
$workerRunning = @(Get-ProjectProcesses 'run_intake_worker')

$portOwner = Get-PortOwner $Port
if ($portOwner -and -not $webRunning.Count) {
    Fail "Port $Port is already used by another program (PID $portOwner), so the website cannot start there." @(
        "Close that program, or start on another port:  scripts\start-demo.ps1 -Port 8001")
}

function Start-Managed([string]$Label, [string[]]$Arguments, [string]$LogName) {
    $stdout = Join-Path $LogDir "$LogName.out.log"
    $stderr = Join-Path $LogDir "$LogName.err.log"
    # cmd.exe does the log redirection so the hidden process does not inherit
    # this script's own output handles (which would keep a caller that reads
    # this script's output through a pipe waiting for ever).
    $inner = '"{0}" "{1}" {2} > "{3}" 2> "{4}"' -f $Python, $Manage, ($Arguments -join ' '), $stdout, $stderr
    $proc = Start-Process -FilePath "$env:ComSpec" -ArgumentList ('/c "' + $inner + '"') -WorkingDirectory $Root `
        -WindowStyle Hidden -PassThru
    Ok "$Label started (PID $($proc.Id)); logs: logs\$LogName.*.log"
    return $proc
}

function Stop-Started {
    foreach ($p in $script:startedProcs) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    # Also stop the interpreter children that a venv launcher may have spawned.
    if ($script:startedWeb) { [void](Stop-ProjectProcesses 'runserver') }
    if ($script:startedWorker) { [void](Stop-ProjectProcesses 'run_intake_worker') }
}

$startedWeb = $false
$startedWorker = $false

if ($webRunning.Count) {
    Ok ('Website already running (PID ' + (($webRunning | ForEach-Object ProcessId) -join ', ') + '); not starting another')
} else {
    $startedProcs += Start-Managed 'Website' @('runserver', "127.0.0.1:$Port", '--noreload') 'web'
    $startedWeb = $true
}

if (-not $workerRunning.Count) {
    # A worker started some other way (another terminal, another interpreter) shows up
    # through the heartbeat it writes: same machine, a live python process, recent.
    $hb = Invoke-Manage @('shell', '-c', "from intake.models import WorkerHeartbeat as W; w = W.objects.order_by('-heartbeat_at').first(); import django.utils.timezone as tz; print('HB|%s|%s|%d' % (w.pid, w.host, (tz.now() - w.heartbeat_at).total_seconds()) if w else 'HB|none')")
    $line = ($hb.Output -split "`r?`n" | Where-Object { $_ -like 'HB|*' } | Select-Object -Last 1)
    if ($line) {
        $parts = $line.Split('|')
        if ($parts.Count -ge 4 -and [int]$parts[3] -lt 120 -and $parts[2] -ieq [Environment]::MachineName) {
            $hbProc = Get-Process -Id ([int]$parts[1]) -ErrorAction SilentlyContinue
            if ($hbProc -and $hbProc.ProcessName -like 'python*') {
                $workerRunning = @([pscustomobject]@{ ProcessId = [int]$parts[1] })
            }
        }
    }
}

if ($workerRunning.Count) {
    Ok ('Worker already running (PID ' + (($workerRunning | ForEach-Object ProcessId) -join ', ') + '); not starting another')
} else {
    # Starting the worker lets it process scrapes that are already waiting in the queue.
    $queueInfo = Invoke-Manage @('intake_status')
    if ($queueInfo.Output -match 'Queued jobs:\s*(\d+)') {
        $waiting = [int]$Matches[1]
        if ($waiting -gt 0) {
            Write-Host "NOTE: $waiting scraper job(s) are already queued. Starting the worker will run them now (public web pages on the approved sources only)." -ForegroundColor Yellow
        }
    }
    $startedProcs += Start-Managed 'Worker' @('run_intake_worker') 'worker'
    $startedWorker = $true
}

# ---------------------------------------------------------- verify startup
$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
$webOk = $false
$workerOk = $false

while ((Get-Date) -lt $deadline -and -not ($webOk -and $workerOk)) {
    Start-Sleep -Seconds 2

    if (-not $webOk) {
        if ($startedWeb -and -not (Get-ProjectProcesses 'runserver')) {
            Show-LogTail (Join-Path $LogDir 'web.err.log')
            Stop-Started
            Fail 'The website stopped right after starting.' @("Details are in logs\web.err.log.")
        }
        try {
            $r = Invoke-WebRequest -Uri $LoginUrl -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { $webOk = $true; Ok "Website is answering at $LoginUrl" }
        } catch { }
    }

    if (-not $workerOk) {
        if ($startedWorker -and -not (Get-ProjectProcesses 'run_intake_worker')) {
            Show-LogTail (Join-Path $LogDir 'worker.err.log')
            Stop-Started
            Fail 'The worker stopped right after starting.' @("Details are in logs\worker.err.log.")
        }
        $st = Invoke-Manage @('intake_status')
        if ($st.Output -match 'Worker:\s+running') { $workerOk = $true; Ok 'Worker has checked in and is waiting for queued jobs' }
    }
}

if (-not $webOk) {
    Show-LogTail (Join-Path $LogDir 'web.err.log')
    Stop-Started
    Fail "The website did not answer within $StartupTimeoutSeconds seconds." @("Details are in logs\web.err.log.")
}
if (-not $workerOk) {
    Show-LogTail (Join-Path $LogDir 'worker.err.log')
    Stop-Started
    Fail "The worker did not check in within $StartupTimeoutSeconds seconds." @("Details are in logs\worker.err.log.")
}

Write-Host ''
Ok 'Demo is running.'
Info "  Website: http://127.0.0.1:$Port/accounts/login/"
Info '  The worker only runs scrapes that an Admin queues on the Scraper page; it never starts one itself.'
Info '  Check:   scripts\start-demo.ps1 -Status'
Info '  Stop:    scripts\start-demo.ps1 -Stop'
if ($OpenBrowser) { Start-Process $LoginUrl }
exit 0
