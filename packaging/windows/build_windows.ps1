param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$DistDir = Join-Path $Root "dist\LocalTTS"
$InstallerScript = Join-Path $PSScriptRoot "local_tts.iss"
$SpecFile = Join-Path $PSScriptRoot "local_tts_gui.spec"

Set-Location $Root

Write-Host "Building LocalTTS desktop app with PyInstaller..."
python -m PyInstaller $SpecFile --noconfirm --clean

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpeg) {
    Copy-Item $ffmpeg.Source (Join-Path $DistDir "ffmpeg.exe") -Force
    Write-Host "Bundled ffmpeg.exe from $($ffmpeg.Source)"
}
else {
    Write-Warning "ffmpeg.exe was not found on PATH. The packaged app will still need ffmpeg installed."
}

$ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
if ($ffprobe) {
    Copy-Item $ffprobe.Source (Join-Path $DistDir "ffprobe.exe") -Force
    Write-Host "Bundled ffprobe.exe from $($ffprobe.Source)"
}
else {
    Write-Warning "ffprobe.exe was not found on PATH. Duration probing will be unavailable in the packaged app."
}

$ffplay = Get-Command ffplay -ErrorAction SilentlyContinue
if ($ffplay) {
    Copy-Item $ffplay.Source (Join-Path $DistDir "ffplay.exe") -Force
    Write-Host "Bundled ffplay.exe from $($ffplay.Source)"
}
else {
    Write-Warning "ffplay.exe was not found on PATH. Inline playback will be unavailable in the packaged app."
}

if ($SkipInstaller) {
    Write-Host "Skipped Inno Setup packaging. Desktop build is ready in $DistDir"
    exit 0
}

$innoCandidates = @(
    $env:ISCC_PATH,
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $innoCandidates) {
    Write-Warning "Inno Setup was not found. Install it or re-run with -SkipInstaller if you only need the dist folder."
    exit 0
}

$iscc = $innoCandidates[0]
Write-Host "Building Windows installer with $iscc..."
& $iscc $InstallerScript

Write-Host "Installer build complete."
