param([switch]$PrepareOnly)

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Revision = 'caaa58ccdcb2529c710219fdd52576bbda84b022'
$Checksum = '120afd561a98d8982af7df0146c1981b3082bb9b77eba1cc8c15a85cb8f2da60'
$Vendor = Join-Path $Root 'native/.vendor/nsh'
$Marker = Join-Path $Vendor '.financial-revision'
if (-not (Test-Path $Marker)) {
    if (Test-Path $Vendor) { throw 'Existing nsh checkout: verify its revision before replacing it.' }
    $Archive = [System.IO.Path]::GetTempFileName()
    try {
        Invoke-WebRequest "https://codeload.github.com/longbridge/nsh/tar.gz/$Revision" -OutFile $Archive
        if ((Get-FileHash $Archive -Algorithm SHA256).Hash.ToLower() -ne $Checksum) { throw 'NSH archive checksum mismatch' }
        New-Item -ItemType Directory -Path $Vendor -Force | Out-Null
        tar -xzf $Archive -C $Vendor --strip-components=1
        if ($LASTEXITCODE -ne 0) { throw 'NSH extraction failed' }
        Set-Content -Path $Marker -Value $Revision
    } finally { Remove-Item $Archive -ErrorAction SilentlyContinue }
}
if ((Get-Content $Marker).Trim() -ne $Revision) { throw 'NSH revision mismatch' }
$Patch = Join-Path $Root 'native/patches/close-guard.patch'
git -C $Vendor apply --reverse --check $Patch 2>$null
if ($LASTEXITCODE -ne 0) {
    git -C $Vendor apply --check $Patch
    if ($LASTEXITCODE -ne 0) { throw 'NSH close guard patch does not apply' }
    git -C $Vendor apply $Patch
    if ($LASTEXITCODE -ne 0) { throw 'NSH close guard patch failed' }
}
if ($PrepareOnly) { return }
$env:RUSTUP_TOOLCHAIN = 'stable'
cargo build --locked --manifest-path (Join-Path $Vendor 'Cargo.toml') -p nsh-cli
if ($LASTEXITCODE -ne 0) { throw 'NSH CLI build failed' }
