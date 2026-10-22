# Install SciPatch on Windows (PowerShell). Windows support is experimental.
#
#   powershell -ExecutionPolicy ByPass -File install.ps1
#
# Options (environment variables):
#   SCIPATCH_SOURCE           install from a git URL, a folder, or PyPI ("scipatch")
#   SCIPATCH_NO_MODIFY_PATH   don't add uv's tool folder to your PATH
#   SCIPATCH_NO_SETUP         don't start 'scipatch setup' afterwards
$ErrorActionPreference = "Stop"

# 1. uv: installs Python and builds each tool's environment.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "==> Installing uv (it manages Python for SciPatch and its tools)..."
    if ($env:SCIPATCH_NO_MODIFY_PATH) { $env:UV_NO_MODIFY_PATH = "1" }
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# 2. SciPatch itself, in its own isolated environment.
$pyproject = Join-Path $PSScriptRoot "pyproject.toml"
if ($env:SCIPATCH_SOURCE) {
    $source = $env:SCIPATCH_SOURCE
} elseif ((Test-Path $pyproject) -and (Select-String -Path $pyproject -Pattern '^name = "scipatch"' -Quiet)) {
    $source = $PSScriptRoot
} else {
    $source = "scipatch"
}
Write-Host "==> Installing SciPatch from $source"
uv tool install --force --python 3.12 $source
if (-not $env:SCIPATCH_NO_MODIFY_PATH) { uv tool update-shell | Out-Null }

$scipatch = Join-Path (uv tool dir --bin) "scipatch.exe"
Write-Host ""
Write-Host "==> SciPatch is installed at $scipatch"

# 3. Guided setup: checks requirements and connects your AI apps.
if (-not $env:SCIPATCH_NO_SETUP) {
    & $scipatch setup
}
Write-Host ""
Write-Host "Open a new terminal window to use the 'scipatch' command."
