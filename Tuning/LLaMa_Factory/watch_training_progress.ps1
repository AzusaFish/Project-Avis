param(
    [int]$PollSeconds = 5
)

$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$sftStatePath = Join-Path $root "outputs\neuro_sft_lora_internvl35_14b\trainer_state.json"
$dpoStatePath = Join-Path $root "outputs\neuro_dpo_lora_internvl35_14b\trainer_state.json"

function Get-TrainProcesses([string]$pattern) {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -eq "python.exe" -and $_.CommandLine -match $pattern
        }
}

function Read-State([string]$statePath) {
    if (-not (Test-Path $statePath)) {
        return $null
    }

    try {
        $raw = Get-Content -Raw -LiteralPath $statePath
        $obj = $raw | ConvertFrom-Json
        $item = [PSCustomObject]@{
            Path       = $statePath
            LastWrite  = (Get-Item -LiteralPath $statePath).LastWriteTime
            GlobalStep = $obj.global_step
            MaxSteps   = $obj.max_steps
            Epoch      = $obj.epoch
        }
        return $item
    }
    catch {
        return $null
    }
}

function Format-ProcLine($proc) {
    $elapsed = (Get-Date) - $proc.CreationDate
    $cpuSec = [math]::Round(($proc.UserModeTime + $proc.KernelModeTime) / 10000000.0, 1)
    $memGB = [math]::Round($proc.WorkingSetSize / 1GB, 2)
    return ("PID={0}  Elapsed={1:hh\:mm\:ss}  CPU={2}s  RAM={3}GB" -f $proc.ProcessId, $elapsed, $cpuSec, $memGB)
}

Write-Host "Training monitor started. Press Ctrl+C to stop." -ForegroundColor Cyan
Write-Host "This is a state monitor, not native tqdm progress output." -ForegroundColor DarkYellow
Write-Host "Root: $root" -ForegroundColor DarkCyan

while ($true) {
    $sftProcs = @(Get-TrainProcesses "llamafactory\.cli train train_neuro_sft_lora.yaml")
    $dpoProcs = @(Get-TrainProcesses "llamafactory\.cli train train_neuro_dpo_lora.yaml")
    $allTrainProcs = @($sftProcs + $dpoProcs)

    $latestTrainStart = $null
    if ($allTrainProcs.Count -gt 0) {
        $latestTrainStart = ($allTrainProcs | Sort-Object CreationDate -Descending | Select-Object -First 1).CreationDate
    }

    $sftState = Read-State $sftStatePath
    $dpoState = Read-State $dpoStatePath

    Clear-Host
    Write-Host ("[{0}] LLaMA-Factory Training Monitor" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")) -ForegroundColor Cyan
    Write-Host ""

    if ($dpoProcs.Count -gt 0) {
        Write-Host "Stage: DPO running" -ForegroundColor Yellow
    }
    elseif ($sftProcs.Count -gt 0) {
        Write-Host "Stage: SFT running" -ForegroundColor Yellow
    }
    else {
        Write-Host "Stage: No active SFT/DPO process detected" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "Active SFT Processes:" -ForegroundColor Magenta
    if ($sftProcs.Count -eq 0) {
        Write-Host "  (none)"
    }
    else {
        foreach ($p in $sftProcs) {
            Write-Host ("  " + (Format-ProcLine $p))
        }
    }

    Write-Host ""
    Write-Host "Active DPO Processes:" -ForegroundColor Magenta
    if ($dpoProcs.Count -eq 0) {
        Write-Host "  (none)"
    }
    else {
        foreach ($p in $dpoProcs) {
            Write-Host ("  " + (Format-ProcLine $p))
        }
    }

    Write-Host ""
    Write-Host "SFT trainer_state:" -ForegroundColor DarkYellow
    if ($null -eq $sftState) {
        Write-Host "  not found"
    }
    else {
        Write-Host ("  global_step={0}/{1}  epoch={2}  updated={3}" -f $sftState.GlobalStep, $sftState.MaxSteps, $sftState.Epoch, $sftState.LastWrite)
        if ($null -ne $latestTrainStart -and $sftState.LastWrite -lt $latestTrainStart.AddMinutes(-1)) {
            Write-Host "  [WARN] trainer_state may be stale (possibly from a previous run)." -ForegroundColor DarkYellow
        }
    }

    Write-Host ""
    Write-Host "DPO trainer_state:" -ForegroundColor DarkYellow
    if ($null -eq $dpoState) {
        Write-Host "  not found"
    }
    else {
        Write-Host ("  global_step={0}/{1}  epoch={2}  updated={3}" -f $dpoState.GlobalStep, $dpoState.MaxSteps, $dpoState.Epoch, $dpoState.LastWrite)
        if ($null -ne $latestTrainStart -and $dpoState.LastWrite -lt $latestTrainStart.AddMinutes(-1)) {
            Write-Host "  [WARN] trainer_state may be stale (possibly from a previous run)." -ForegroundColor DarkYellow
        }
    }

    Write-Host ""
    Write-Host ("Polling every {0}s ..." -f $PollSeconds) -ForegroundColor DarkGray

    Start-Sleep -Seconds ([math]::Max(1, $PollSeconds))
}
