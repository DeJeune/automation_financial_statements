#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
case "${1:-check}" in
  format)
    ./scripts/biome.sh format --write
    cargo fmt --manifest-path native/Cargo.toml -p financial-engine -p financial-desktop
    ;;
  check)
    ./scripts/biome.sh check --error-on-warnings
    cargo fmt --manifest-path native/Cargo.toml -p financial-engine -p financial-desktop --check
    cargo clippy --locked --manifest-path native/Cargo.toml -p financial-engine -p financial-desktop --all-targets -- -D warnings
    native/.vendor/nsh/target/debug/nsh check native/app/App.tsx
    ;;
  *) echo 'Usage: scripts/check-native.sh [check|format]' >&2; exit 2 ;;
esac
