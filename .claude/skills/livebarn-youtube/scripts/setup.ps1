# One-time setup for the livebarn-youtube skill: fetch a static ffmpeg build into ..\bin
# and install the googleapis npm package (used only by the upload step).
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$bin  = Join-Path $root 'bin'
New-Item -ItemType Directory -Force $bin | Out-Null
New-Item -ItemType Directory -Force (Join-Path $env:LOCALAPPDATA "livebarn-youtube\secrets") | Out-Null  # OAuth files live here, outside the repo

$haveFfmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or (Test-Path (Join-Path $bin 'ffmpeg.exe'))
if (-not $haveFfmpeg) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $zip = Join-Path $env:TEMP 'ffmpeg-release-essentials.zip'
    $ex  = Join-Path $env:TEMP 'ffmpeg-extract'
    Write-Host 'Downloading ffmpeg (gyan.dev release-essentials, ~90 MB)...'
    Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $zip
    if (Test-Path $ex) { Remove-Item -Recurse -Force $ex }
    Expand-Archive $zip -DestinationPath $ex
    Get-ChildItem $ex -Recurse -Include ffmpeg.exe, ffprobe.exe | ForEach-Object { Copy-Item $_.FullName $bin -Force }
    Remove-Item $zip -Force
    Remove-Item -Recurse -Force $ex
    Write-Host "ffmpeg installed to $bin"
} else {
    Write-Host 'ffmpeg already available.'
}

if (-not (Test-Path (Join-Path $root 'node_modules\googleapis'))) {
    Write-Host 'Installing googleapis (for YouTube upload)...'
    Push-Location $root
    try { npm install --no-audit --no-fund --loglevel error } finally { Pop-Location }
} else {
    Write-Host 'googleapis already installed.'
}

Write-Host ''
node (Join-Path $PSScriptRoot 'livebarn.mjs') doctor
