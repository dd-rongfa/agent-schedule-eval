# run_hallucination.ps1 — 幻觉鲁棒性实验 runner
# 用法:
#   .\run_hallucination.ps1                   # 默认: t=0.1 x3 + t=0.7 x3, 4 模型
#   .\run_hallucination.ps1 -Temps 0.1        # 只跑 t=0.1
#   .\run_hallucination.ps1 -Rounds 1         # 每温度只跑 1 轮
#   .\run_hallucination.ps1 -Models "deepseek-chat","mimo-v2-pro"  # 指定模型

param(
    [string[]]$Models  = @("deepseek-chat", "deepseek-reasoner", "mimo-v2-pro", "doubao-seed-2-0-pro-260215"),
    [double[]]$Temps   = @(0.1, 0.7),
    [int]$Rounds       = 3
)

$Python = "d:\project\llm_as_a_judge\.venv\Scripts\python.exe"
$Script = "$PSScriptRoot\eval\test_action_hallucination.py"

$total = $Models.Count * $Temps.Count * $Rounds
$done  = 0

Write-Host "============================================================"
Write-Host "Hallucination Robustness Experiment"
Write-Host "  Models:       $($Models -join ', ')"
Write-Host "  Temperatures: $($Temps -join ', ')"
Write-Host "  Rounds:       $Rounds"
Write-Host "  Total runs:   $total"
Write-Host "============================================================"
Write-Host ""

foreach ($temp in $Temps) {
    foreach ($round in 1..$Rounds) {
        Write-Host "--- Temperature=$temp  Round=$round/$Rounds ---" -ForegroundColor Cyan

        # 同温度同轮次的 4 个模型并行
        $jobs = @()
        foreach ($model in $Models) {
            $jobs += Start-Job -ScriptBlock {
                param($py, $sc, $m, $t)
                $env:TARGET_MODEL = $m
                $env:TEMPERATURE  = $t
                & $py $sc 2>&1
            } -ArgumentList $Python, $Script, $model, $temp
        }

        # 等所有模型跑完
        $jobs | Wait-Job | ForEach-Object {
            $output = Receive-Job $_
            # 打印最后 5 行摘要
            $lines = ($output -split "`n") | Where-Object { $_.Trim() -ne "" }
            $summary = $lines | Select-Object -Last 8
            Write-Host ($summary -join "`n")
            Write-Host ""
            Remove-Job $_
        }

        $done += $Models.Count
        Write-Host "  Progress: $done / $total runs completed" -ForegroundColor Green
        Write-Host ""
    }
}

Write-Host "============================================================"
Write-Host "All $total runs completed."
Write-Host "Results: v2_tool_eval/results/hallucination/"
Write-Host "Merged:  v2_tool_eval/results/hallucination/merged.jsonl"
Write-Host "============================================================"
