$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Version = '2.6.2'
$Checksum = '283639d771d82502b7498e87cee2e703f84aa040144b04ea1bcfc0ab942a9184'
$Cache = Join-Path $Root 'native/.tools'
$Exe = Join-Path $Cache "biome-$Version.exe"
New-Item -ItemType Directory -Force $Cache | Out-Null
if (-not (Test-Path $Exe)) {
    $Download = Join-Path $Cache 'biome-download.tmp'
    try {
        Invoke-WebRequest "https://github.com/biomejs/biome/releases/download/%40biomejs/biome%40$Version/biome-win32-x64.exe" -OutFile $Download
        if ((Get-FileHash $Download -Algorithm SHA256).Hash.ToLower() -ne $Checksum) { throw 'Biome checksum mismatch' }
        Move-Item $Download $Exe -Force
    } finally { Remove-Item $Download -ErrorAction SilentlyContinue }
}
if ((Get-FileHash $Exe -Algorithm SHA256).Hash.ToLower() -ne $Checksum) { throw 'Biome checksum mismatch' }
Push-Location $Root
try { & $Exe @args; $Code = $LASTEXITCODE } finally { Pop-Location }
exit $Code
