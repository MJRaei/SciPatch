# Install Motel on Windows (PowerShell). Windows support is experimental.
#
#   powershell -ExecutionPolicy ByPass -File install.ps1
#
# Options (environment variables):
#   MOTEL_SOURCE           install from a git URL, a folder, or PyPI ("motel")
#   MOTEL_NO_MODIFY_PATH   don't add uv's tool folder to your PATH
#   MOTEL_NO_SETUP         don't start 'motel setup' afterwards
$ErrorActionPreference = "Stop"

# 1. uv: installs Python and builds each tool's environment.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "==> Installing uv (it manages Python for Motel and its tools)..."
    if ($env:MOTEL_NO_MODIFY_PATH) { $env:UV_NO_MODIFY_PATH = "1" }
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# 2. Motel itself, in its own isolated environment.
$pyproject = Join-Path $PSScriptRoot "pyproject.toml"
if ($env:MOTEL_SOURCE) {
    $source = $env:MOTEL_SOURCE
} elseif ((Test-Path $pyproject) -and (Select-String -Path $pyproject -Pattern '^name = "motel"' -Quiet)) {
    $source = $PSScriptRoot
} else {
    $source = "motel"
}
Write-Host "==> Installing Motel from $source"
uv tool install --force --python 3.12 $source
if (-not $env:MOTEL_NO_MODIFY_PATH) { uv tool update-shell | Out-Null }

$motel = Join-Path (uv tool dir --bin) "motel.exe"
Write-Host ""
Write-Host "==> Motel is installed at $motel"

# 3. Guided setup: checks requirements and connects your AI apps.
if (-not $env:MOTEL_NO_SETUP) {
    & $motel setup
}
Write-Host ""
Write-Host "Open a new terminal window to use the 'motel' command."
