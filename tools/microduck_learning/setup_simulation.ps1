[CmdletBinding()]
param(
    [ValidateSet("Inference", "Smoke")]
    [string]$Mode = "Smoke",
    [string]$TrainingDir = "",
    [string]$Ref = "29e887ecfbf5d37144759e5a9f8a176dfb83d547",
    [string]$Remote = "https://github.com/pollen-robotics/microduck_rl.git",
    [string]$WalkingPolicy = "",
    [string]$BamJsonPath = "",
    [string]$BamActuator = "hl2915",
    [string]$BamModel = "m6",
    [switch]$SkipSync,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Format-Command {
    param(
        [Parameter(Mandatory)] [string]$Executable,
        [Parameter(Mandatory)] [string[]]$Arguments
    )

    $parts = @($Executable) + $Arguments
    ($parts | ForEach-Object {
        $text = [string]$_
        if ($text -match '[\s"]') {
            '"' + $text.Replace('"', '\"') + '"'
        } else {
            $text
        }
    }) -join ' '
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)] [string]$Executable,
        [Parameter(Mandatory)] [string[]]$Arguments,
        [Parameter(Mandatory)] [string]$WorkingDirectory
    )

    Push-Location $WorkingDirectory
    try {
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "命令失败（退出码 $LASTEXITCODE）：$(Format-Command $Executable $Arguments)"
        }
    } finally {
        Pop-Location
    }
}

function Invoke-Captured {
    param(
        [Parameter(Mandatory)] [string]$Executable,
        [Parameter(Mandatory)] [string[]]$Arguments,
        [Parameter(Mandatory)] [string]$WorkingDirectory
    )

    Push-Location $WorkingDirectory
    try {
        $output = @(& $Executable @Arguments 2>&1)
        if ($LASTEXITCODE -ne 0) {
            $detail = ($output | ForEach-Object { [string]$_ }) -join "`n"
            throw "命令失败（退出码 $LASTEXITCODE）：$(Format-Command $Executable $Arguments)`n$detail"
        }
        return ($output | ForEach-Object { [string]$_ }) -join "`n"
    } finally {
        Pop-Location
    }
}

function Require-Tool {
    param([Parameter(Mandatory)] [string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "找不到 $Name。请先安装 $Name，并确认它在 PATH 中。"
    }
}

try {
    $workspace = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    if ([string]::IsNullOrWhiteSpace($TrainingDir)) {
        $TrainingDir = Join-Path (Split-Path $workspace -Parent) "microduck_rl"
    }
    $trainingPath = [IO.Path]::GetFullPath($TrainingDir)

    if ($Mode -eq "Inference" -and [string]::IsNullOrWhiteSpace($WalkingPolicy)) {
        throw "Inference 模式必须提供 -WalkingPolicy <ONNX 文件路径>。"
    }
    $runningWindows = ($IsWindows -or $env:OS -eq "Windows_NT")
    if (-not $DryRun -and $runningWindows) {
        throw "实际仿真/训练请在 WSL2 或 Linux 中运行；Windows 入口只支持 -DryRun 路径检查。这样可以避免 POSIX 终端和 Linux .venv 兼容性错误。"
    }
    $walkingPath = if ([string]::IsNullOrWhiteSpace($WalkingPolicy)) {
        ""
    } else {
        [IO.Path]::GetFullPath($WalkingPolicy)
    }
    $bamJsonPath = if ([string]::IsNullOrWhiteSpace($BamJsonPath)) {
        ""
    } else {
        [IO.Path]::GetFullPath($BamJsonPath)
    }
    if ($Mode -eq "Inference" -and $bamJsonPath) {
        throw "-BamJsonPath 目前只用于 Smoke；上游 infer_policy.py 仍固定使用官方 XL330 BAM。"
    }

    $bamContractPath = Join-Path $workspace "tools\microduck_learning\check_bam_model.py"
    $bamContractOutput = Join-Path $workspace "artifacts\bam-model-$BamActuator-$BamModel.json"
    $bamContractCommand = @(
        "run", "python", $bamContractPath, $bamJsonPath,
        "--actuator", $BamActuator,
        "--model", $BamModel,
        "--json-out", $bamContractOutput
    )

    $syncCommand = @("sync")
    $probeCommand = @("run", "scripts/infer_policy.py", "--help")
    $modeCommand = if ($Mode -eq "Inference") {
        @("run", "scripts/infer_policy.py", "--walking", $walkingPath, "--new-cmd-obs")
    } else {
        @(
            "run", "train", "Mjlab-Velocity-Flat-MicroDuck",
            "--gpu-ids", "None",
            "--env.scene.num-envs", "8",
            "--agent.num-steps-per-env", "24",
            "--agent.max-iterations", "5",
            "--agent.logger", "tensorboard",
            "--agent.upload-model", "False",
            "--agent.run-name", "lesson-01-repro"
        )
    }

    if ($Mode -eq "Smoke" -and $bamJsonPath) {
        $modeCommand += @(
            "--env.scene.entities.robot.articulation.actuators.0.motor-name", "None",
            "--env.scene.entities.robot.articulation.actuators.0.model", "None",
            "--env.scene.entities.robot.articulation.actuators.0.json-path", $bamJsonPath
        )
    }

    if ($DryRun) {
        Write-Output "TrainingDir: $trainingPath"
        Write-Output "Mode: $Mode"
        if (Test-Path -LiteralPath $trainingPath -PathType Container) {
            Write-Output (Format-Command "git" @("-C", $trainingPath, "checkout", "--detach", $Ref))
        } else {
            Write-Output (Format-Command "git" @("clone", $Remote, $trainingPath))
            Write-Output (Format-Command "git" @("-C", $trainingPath, "checkout", "--detach", $Ref))
        }
        if ($SkipSync) {
            Write-Output "(skip) uv sync"
        } else {
            Write-Output (Format-Command "uv" $syncCommand)
        }
        if ($bamJsonPath) {
            Write-Output "BAM JSON: $bamJsonPath"
            Write-Output (Format-Command "uv" $bamContractCommand)
        }
        Write-Output (Format-Command "uv" $probeCommand)
        Write-Output (Format-Command "uv" $modeCommand)
        exit 0
    }

    Require-Tool "git"
    Require-Tool "uv"

    if ($Mode -eq "Inference" -and -not (Test-Path -LiteralPath $walkingPath -PathType Leaf)) {
        throw "找不到 walking ONNX 文件：$walkingPath"
    }
    if ($bamJsonPath -and -not (Test-Path -LiteralPath $bamJsonPath -PathType Leaf)) {
        throw "找不到 BAM JSON 文件：$bamJsonPath"
    }

    if (-not (Test-Path -LiteralPath $trainingPath)) {
        $parent = Split-Path $trainingPath -Parent
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Invoke-Checked "git" @("clone", $Remote, $trainingPath) $workspace
    } elseif (-not (Test-Path -LiteralPath $trainingPath -PathType Container)) {
        throw "训练路径存在但不是目录：$trainingPath"
    } else {
        $root = Invoke-Captured "git" @("-C", $trainingPath, "rev-parse", "--show-toplevel") $workspace
        if ([string]::IsNullOrWhiteSpace($root)) {
            throw "训练路径不是 Git 工作区：$trainingPath"
        }
        # `git status` can report every file as modified on a Windows/WSL shared drive when
        # only line endings or filesystem mtimes differ. Compare content, then check untracked
        # files separately so a real local edit is still protected without blocking a clean checkout.
        & git -C $trainingPath diff --quiet
        $worktreeDiff = $LASTEXITCODE
        & git -C $trainingPath diff --cached --quiet
        $indexDiff = $LASTEXITCODE
        $untracked = @(& git -C $trainingPath ls-files --others --exclude-standard)
        if ($worktreeDiff -ne 0 -or $indexDiff -ne 0 -or $untracked.Count -gt 0) {
            $details = @()
            if ($worktreeDiff -ne 0) {
                $details += (Invoke-Captured "git" @("-C", $trainingPath, "diff", "--name-only") $workspace)
            }
            if ($indexDiff -ne 0) {
                $details += (Invoke-Captured "git" @("-C", $trainingPath, "diff", "--cached", "--name-only") $workspace)
            }
            if ($untracked.Count -gt 0) {
                $details += $untracked
            }
            throw "训练仓库有未提交修改，已停止以保护用户文件：$trainingPath`n$($details -join "`n")"
        }
    }

    Invoke-Checked "git" @("-C", $trainingPath, "checkout", "--detach", $Ref) $workspace
    if (-not $SkipSync) {
        Invoke-Checked "uv" $syncCommand $trainingPath
    }
    if ($bamJsonPath) {
        Invoke-Checked "uv" $bamContractCommand $trainingPath
    }
    Invoke-Checked "uv" $probeCommand $trainingPath

    Invoke-Checked "uv" $modeCommand $trainingPath
    Write-Output "仿真命令完成：$Mode"
} catch {
    $message = $_.Exception.Message
    if ($message -match "termios") {
        $message += "`n上游训练脚本需要 POSIX 环境；请在 WSL2/Linux 中运行同一条 uv 命令。"
    }
    Write-Error $message
    exit 1
}
