$ErrorActionPreference = "Stop"

$Repository = if ($env:MINDMAP_REPOSITORY) { $env:MINDMAP_REPOSITORY } else { "erd0s/mindmap" }
$InstallDir = if ($env:MINDMAP_INSTALL_DIR) { $env:MINDMAP_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "Mindmap\bin" }
$BaseUrl = if ($env:MINDMAP_RELEASE_URL) { $env:MINDMAP_RELEASE_URL } else { "https://github.com/$Repository/releases/latest/download" }

$Architecture = switch ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture) {
    "X64" { "amd64" }
    "Arm64" { "arm64" }
    "X86" { "386" }
    default { throw "Unsupported Windows architecture: $_" }
}

$Asset = "mindmap_windows_$Architecture.exe"
$TemporaryDir = Join-Path ([System.IO.Path]::GetTempPath()) ("mindmap-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $TemporaryDir | Out-Null
try {
    $Download = Join-Path $TemporaryDir $Asset
    $Checksums = Join-Path $TemporaryDir "checksums.txt"
    Invoke-WebRequest -UseBasicParsing "$BaseUrl/$Asset" -OutFile $Download
    Invoke-WebRequest -UseBasicParsing "$BaseUrl/checksums.txt" -OutFile $Checksums
    $Line = Get-Content $Checksums | Where-Object { $_ -match "\s$([regex]::Escape($Asset))$" } | Select-Object -First 1
    if (-not $Line) { throw "Release checksum for $Asset was not found" }
    $Expected = ($Line -split "\s+")[0].ToLowerInvariant()
    $Actual = (Get-FileHash -Algorithm SHA256 $Download).Hash.ToLowerInvariant()
    if ($Expected -ne $Actual) { throw "Checksum verification failed" }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $Destination = Join-Path $InstallDir "mindmap.exe"
    Move-Item -Force $Download $Destination
    Write-Host "Installed mindmap to $Destination"
    Write-Host "Windows currently supports the terminal viewer. Agent hooks and Mindmap Desktop are macOS/Linux follow-up work."
    if (($env:PATH -split ';') -notcontains $InstallDir) {
        Write-Host "Add $InstallDir to PATH, then open a new terminal."
    }
}
finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $TemporaryDir
}
