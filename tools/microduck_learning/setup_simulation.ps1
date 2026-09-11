[CmdletBinding()]
param(
    [ValidateSet("Inference", "Smoke")]
    [string]$Mode = "Smoke",
    [string]$TrainingDir = "",
    [string]$Ref = "29e887ecfbf5d37144759e5a9f8a176dfb83d547",
    [string]$Remote = "https://github.com/pollen-robotics/microduck_rl.git",
    [string]$WalkingPolicy = "",
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
    $walkingPath = if ([string]::IsNullOrWhiteSpace($WalkingPolicy)) {
        ""
    } else {
        [IO.Path]::GetFullPath($WalkingPolicy)
    }

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

    if ($DryRun) {
        Write-Output "TrainingDir: $trainingPath"
        Write-Output "Mode: $Mode"
        if (Test-Path -LiteralPath $trainingPath -PathType Container) {
            Write-Output (Format-Command "git -C $trainingPath" @("checkout", "--detach", $Ref))
        } else {
            Write-Output (Format-Command "git" @("clone", $Remote, $trainingPath))
            Write-Output (Format-Command "git -C $trainingPath" @("checkout", "--detach", $Ref))
        }
        if ($SkipSync) {
            Write-Output "(skip) uv sync"
        } else {
            Write-Output (Format-Command "uv" $syncCommand)
        }
        Write-Output (Format-Command "uv" $probeCommand)
        Write-Output (Format-Command "uv" $modeCommand)
        exit 0
    }

    Require-Tool "git"
    Require-Tool "uv"

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
        $dirty = Invoke-Captured "git" @("-C", $trainingPath, "status", "--porcelain") $workspace
        if (-not [string]::IsNullOrWhiteSpace($dirty)) {
            throw "训练仓库有未提交修改，已停止以保护用户文件：$trainingPath`n$dirty"
        }
    }

    Invoke-Checked "git" @("-C", $trainingPath, "checkout", "--detach", $Ref) $workspace
    if (-not $SkipSync) {
        Invoke-Checked "uv" $syncCommand $trainingPath
    }
    Invoke-Checked "uv" $probeCommand $trainingPath

    if ($Mode -eq "Inference" -and -not (Test-Path -LiteralPath $walkingPath -PathType Leaf)) {
        throw "找不到 walking ONNX 文件：$walkingPath"
    }
    Invoke-Checked "uv" $modeCommand $trainingPath
    Write-Output "仿真命令完成：$Mode"
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
