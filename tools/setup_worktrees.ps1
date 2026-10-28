# =============================================================================
# setup_worktrees.ps1 - Quan ly cac ban lam viec song song (git worktree)
# Cho du an CO NGU (VietModHub).
#
# Muc dich: Moi AI Agent lam viec tren mot BAN SAO DAY DU cua du an,
# nam trong mot thu muc rieng, tren mot NHANH (branch) rieng.
# Nho vay cac Agent khong bao gio ghi de code cua nhau.
#
# CACH DUNG (mo PowerShell tai thu muc goc du an):
#   .\tools\setup_worktrees.ps1 -Status
#   .\tools\setup_worktrees.ps1 -Create scanner,ui,cloud
#   .\tools\setup_worktrees.ps1 -Cleanup scanner,ui,cloud
# =============================================================================

param(
    [switch]$Status,
    [string[]]$Create = @(),
    [string[]]$Cleanup = @()
)

$ErrorActionPreference = "Stop"

# Thu muc goc du an (script nam trong tools\, lui len 1 cap)
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ParentDir = Split-Path -Parent $RepoRoot
$RepoName = Split-Path -Leaf $RepoRoot
$VenvPython = Join-Path $ParentDir ".venv\Scripts\python.exe"

Set-Location $RepoRoot

function Test-GitRepo {
    $ok = (git rev-parse --is-inside-work-tree 2>$null)
    if ($ok -ne "true") {
        Write-Host "[!] Thu muc nay khong phai git repo!" -ForegroundColor Red
        exit 1
    }
}

# Cho phep nhap "scanner,ui,cloud" du chay bang -File hay -Command deu dung
function Split-TaskNames {
    param([string[]]$Values)
    $out = @()
    foreach ($v in $Values) {
        if ([string]::IsNullOrWhiteSpace($v)) { continue }
        foreach ($piece in ($v -split ",")) {
            $p = $piece.Trim()
            if ($p) { $out += $p }
        }
    }
    return $out
}

function Show-WorktreeStatus {
    Write-Host ""
    Write-Host "=== TRANG THAI CAC BAN LAM VIEC (WORKTREE) ===" -ForegroundColor Cyan
    git worktree prune
    $list = git worktree list
    if ($list) { $list | ForEach-Object { Write-Host "  $_" } }

    Write-Host ""
    Write-Host "=== CAC NHANH HIEN CO ===" -ForegroundColor Cyan
    $branches = git branch --list
    if ($branches) { $branches | ForEach-Object { Write-Host "  $_" } }

    Write-Host ""
    Write-Host "=== THAY DOI CHUA LUU (COMMIT) ===" -ForegroundColor Cyan
    $dirty = git status --porcelain
    if ($dirty) {
        Write-Host "  Co thay doi chua luu!" -ForegroundColor Yellow
        Write-Host "  -> Ban nen commit truoc khi tao worktree moi," -ForegroundColor Yellow
        Write-Host "     neu khong ban sao se KHONG co cac thay doi nay." -ForegroundColor Yellow
    } else {
        Write-Host "  Sach se (khong co thay doi nao chua luu)." -ForegroundColor Green
    }
    Write-Host ""
}

function New-TaskWorktree {
    param([string[]]$Names)

    $Names = Split-TaskNames $Names

    if (-not $Names -or $Names.Count -eq 0) {
        Write-Host "[!] Ban chua nhap ten task. Vi du: -Create scanner,ui,cloud" -ForegroundColor Red
        return
    }

    Show-WorktreeStatus

    foreach ($name in $Names) {
        $name = $name.Trim()
        if (-not $name) { continue }

        $branch = "task/$name"
        $dir = Join-Path $ParentDir "$RepoName-$name"

        if (Test-Path $dir) {
            Write-Host "[=] Da ton tai, bo qua: $dir" -ForegroundColor Yellow
            continue
        }

        $branchExists = (git branch --list $branch)
        if ($branchExists) {
            Write-Host "[*] Nhanh '$branch' da co, dung lai nhanh cu..." -ForegroundColor Cyan
            git worktree add "$dir" $branch | Out-Null
        } else {
            Write-Host "[*] Tao nhanh moi '$branch'..." -ForegroundColor Cyan
            git worktree add "$dir" -b $branch | Out-Null
        }

        if (Test-Path $dir) {
            Write-Host "[OK] Da tao: $dir  (nhanh: $branch)" -ForegroundColor Green
            Write-Host "     Agent mo thu muc: $dir" -ForegroundColor Gray
            if (Test-Path $VenvPython) {
                Write-Host "     Chay thu app: `"$VenvPython`" app.py --server" -ForegroundColor Gray
            } else {
                Write-Host "     Chay thu app: python app.py --server" -ForegroundColor Gray
            }
        } else {
            Write-Host "[!] Tao that bai: $dir" -ForegroundColor Red
        }
    }

    Write-Host ""
    Write-Host "=== HOAN TAT ===" -ForegroundColor Green
    Write-Host "Gop code sau khi Agent lam xong:" -ForegroundColor Cyan
    foreach ($name in $Names) {
        Write-Host "  cd `"$(Join-Path $ParentDir "$RepoName-$name")`"; git add -A; git commit -m `"feat: ...`"" -ForegroundColor Gray
        Write-Host "  cd `"$RepoRoot`"; git merge task/$name" -ForegroundColor Gray
    }
    Write-Host ""
}

function Remove-TaskWorktree {
    param([string[]]$Names)

    $Names = Split-TaskNames $Names

    if (-not $Names -or $Names.Count -eq 0) {
        Write-Host "[!] Ban chua nhap ten task. Vi du: -Cleanup scanner,ui" -ForegroundColor Red
        return
    }

    foreach ($name in $Names) {
        $name = $name.Trim()
        if (-not $name) { continue }

        $branch = "task/$name"
        $dir = Join-Path $ParentDir "$RepoName-$name"

        Write-Host "[*] Dang don dep: $name ..." -ForegroundColor Cyan
        git worktree remove --force "$dir" 2>$null
        git branch -D $branch 2>$null
        Write-Host "[OK] Da xoa ban lam viec va nhanh '$branch'." -ForegroundColor Green
    }

    git worktree prune
    Write-Host ""
    Show-WorktreeStatus
}

Test-GitRepo

if ($Create.Count -gt 0) {
    New-TaskWorktree -Names $Create
    exit 0
}

if ($Cleanup.Count -gt 0) {
    Remove-TaskWorktree -Names $Cleanup
    exit 0
}

# Mac dinh: chi hien thi trang thai
Show-WorktreeStatus
Write-Host "Goi y lenh tiep theo:" -ForegroundColor Cyan
Write-Host "  .\tools\setup_worktrees.ps1 -Create scanner,ui,cloud" -ForegroundColor Gray
Write-Host "  .\tools\setup_worktrees.ps1 -Cleanup scanner,ui,cloud" -ForegroundColor Gray
Write-Host ""
