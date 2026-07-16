param(
    [string]$Version = "",
    [switch]$SkipExeInstaller,
    [switch]$SkipMsi,
    [switch]$SkipPortableZip
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$DistDir = Join-Path $Root "dist\LocalTTS"
$InstallerOutputDir = Join-Path $Root "dist-installer"
$ExeInstallerScript = Join-Path $PSScriptRoot "local_tts.iss"
$MsiInstallerScript = Join-Path $PSScriptRoot "local_tts.wxs"
$SpecFile = Join-Path $PSScriptRoot "local_tts_gui.spec"
$WixBuildDir = Join-Path $Root "build\wix"

function Resolve-Version {
    param([string]$RequestedVersion)

    $candidate = $RequestedVersion
    if (-not $candidate) {
        $candidate = $env:LOCAL_TTS_VERSION
    }
    if (-not $candidate) {
        $candidate = "0.1.0"
    }

    if ($candidate.StartsWith("v")) {
        $candidate = $candidate.Substring(1)
    }

    if ($candidate -notmatch '^\d+\.\d+\.\d+$') {
        throw "Version '$candidate' is invalid. Use a three-part numeric version like 0.1.0."
    }

    return $candidate
}

function Resolve-ExecutablePath {
    param([string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        if (-not $candidate) {
            continue
        }

        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }

        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command -and $command.Source) {
            return $command.Source
        }
    }

    return $null
}

function Bundle-OptionalBinary {
    param(
        [string]$CommandName,
        [string]$DestinationFileName,
        [string]$MissingMessage
    )

    $source = Resolve-ExecutablePath -Candidates @($CommandName)
    if ($source) {
        Copy-Item $source (Join-Path $DistDir $DestinationFileName) -Force
        Write-Host "Bundled $DestinationFileName from $source"
        return
    }

    Write-Warning $MissingMessage
}

$Version = Resolve-Version -RequestedVersion $Version
$ExeInstallerBaseName = "LocalTTS-Setup-$Version"
$MsiInstallerFileName = "LocalTTS-$Version.msi"
$PortableZipFileName = "LocalTTS-portable-$Version.zip"

Set-Location $Root
New-Item -ItemType Directory -Force -Path $InstallerOutputDir | Out-Null

Write-Host "Building LocalTTS desktop app with PyInstaller..."
python -m PyInstaller $SpecFile --noconfirm --clean

Bundle-OptionalBinary `
    -CommandName "ffmpeg" `
    -DestinationFileName "ffmpeg.exe" `
    -MissingMessage "ffmpeg.exe was not found on PATH. The packaged app will still need ffmpeg installed."

Bundle-OptionalBinary `
    -CommandName "ffprobe" `
    -DestinationFileName "ffprobe.exe" `
    -MissingMessage "ffprobe.exe was not found on PATH. Duration probing will be unavailable in the packaged app."

Bundle-OptionalBinary `
    -CommandName "ffplay" `
    -DestinationFileName "ffplay.exe" `
    -MissingMessage "ffplay.exe was not found on PATH. Inline playback will be unavailable in the packaged app."

if (-not $SkipPortableZip) {
    $portableZipPath = Join-Path $InstallerOutputDir $PortableZipFileName
    if (Test-Path $portableZipPath) {
        Remove-Item $portableZipPath -Force
    }

    Compress-Archive -Path $DistDir -DestinationPath $portableZipPath -Force
    Write-Host "Portable ZIP created at $portableZipPath"
}

if (-not $SkipExeInstaller) {
    $iscc = Resolve-ExecutablePath -Candidates @(
        $env:ISCC_PATH,
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        "ISCC.exe"
    )

    if (-not $iscc) {
        Write-Warning "Inno Setup was not found. Install it or re-run with -SkipExeInstaller if you only need the app folder, ZIP, or MSI."
    }
    else {
        Write-Host "Building EXE installer with $iscc..."
        & $iscc "/DMyAppVersion=$Version" "/DMyOutputBaseFilename=$ExeInstallerBaseName" $ExeInstallerScript
    }
}

if (-not $SkipMsi) {
    $heat = Resolve-ExecutablePath -Candidates @(
        $env:WIX_HEAT_PATH,
        (Join-Path ${env:ProgramFiles(x86)} "WiX Toolset v3.11\bin\heat.exe"),
        (Join-Path $env:ProgramFiles "WiX Toolset v3.11\bin\heat.exe"),
        "heat.exe"
    )
    $candle = Resolve-ExecutablePath -Candidates @(
        $env:WIX_CANDLE_PATH,
        (Join-Path ${env:ProgramFiles(x86)} "WiX Toolset v3.11\bin\candle.exe"),
        (Join-Path $env:ProgramFiles "WiX Toolset v3.11\bin\candle.exe"),
        "candle.exe"
    )
    $light = Resolve-ExecutablePath -Candidates @(
        $env:WIX_LIGHT_PATH,
        (Join-Path ${env:ProgramFiles(x86)} "WiX Toolset v3.11\bin\light.exe"),
        (Join-Path $env:ProgramFiles "WiX Toolset v3.11\bin\light.exe"),
        "light.exe"
    )

    if (-not ($heat -and $candle -and $light)) {
        Write-Warning "WiX Toolset 3 was not found. Install it or re-run with -SkipMsi if you only need the app folder, ZIP, or EXE installer."
    }
    else {
        $harvestFile = Join-Path $WixBuildDir "LocalTTS.Files.wxs"
        $wixObjectsDir = Join-Path $WixBuildDir "obj"
        $msiOutputPath = Join-Path $InstallerOutputDir $MsiInstallerFileName

        Remove-Item $WixBuildDir -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $WixBuildDir, $wixObjectsDir | Out-Null

        Write-Host "Harvesting application files for MSI packaging..."
        & $heat dir $DistDir `
            -cg LocalTTSFiles `
            -gg `
            -scom `
            -sreg `
            -sfrag `
            -srd `
            -dr INSTALLDIR `
            -var var.SourceDir `
            -out $harvestFile

        Write-Host "Compiling WiX sources..."
        & $candle `
            -nologo `
            -arch x64 `
            "-dSourceDir=$DistDir" `
            "-dProductVersion=$Version" `
            -out "$wixObjectsDir\" `
            $MsiInstallerScript `
            $harvestFile

        $mainObject = Join-Path $wixObjectsDir ([System.IO.Path]::GetFileNameWithoutExtension($MsiInstallerScript) + ".wixobj")
        $harvestObject = Join-Path $wixObjectsDir ([System.IO.Path]::GetFileNameWithoutExtension($harvestFile) + ".wixobj")

        Write-Host "Linking MSI package..."
        & $light `
            -nologo `
            -ext WixUIExtension `
            -out $msiOutputPath `
            $mainObject `
            $harvestObject

        Write-Host "MSI installer created at $msiOutputPath"
    }
}

Write-Host "Windows packaging completed."
