param([ValidateSet('check', 'format')][string]$Mode = 'check')
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
Push-Location $Root
try {
    if ($Mode -eq 'format') {
        & ./scripts/biome.ps1 format --write
        if ($LASTEXITCODE -ne 0) { throw 'Biome formatting failed' }
        cargo fmt --manifest-path native/Cargo.toml -p financial-engine -p financial-desktop
        if ($LASTEXITCODE -ne 0) { throw 'Rust formatting failed' }
    } else {
        & ./scripts/biome.ps1 check --error-on-warnings
        if ($LASTEXITCODE -ne 0) { throw 'Biome check failed' }
        cargo fmt --manifest-path native/Cargo.toml -p financial-engine -p financial-desktop --check
        if ($LASTEXITCODE -ne 0) { throw 'Rust formatting check failed' }
        cargo clippy --locked --manifest-path native/Cargo.toml -p financial-engine -p financial-desktop --all-targets -- -D warnings
        if ($LASTEXITCODE -ne 0) { throw 'Clippy failed' }
        & native/.vendor/nsh/target/debug/nsh.exe check native/app/App.tsx
        if ($LASTEXITCODE -ne 0) { throw 'NSH type checking failed' }
    }
} finally { Pop-Location }
