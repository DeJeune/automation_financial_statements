#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
revision=caaa58ccdcb2529c710219fdd52576bbda84b022
checksum=120afd561a98d8982af7df0146c1981b3082bb9b77eba1cc8c15a85cb8f2da60
vendor="$root/native/.vendor"
mkdir -p "$vendor"
if [ ! -f "$vendor/nsh/.financial-revision" ]; then
  if [ -e "$vendor/nsh" ]; then
    echo 'Existing native/.vendor/nsh checkout: verify its revision before replacing it.' >&2
    exit 1
  fi
  archive=$(mktemp)
  trap 'rm -f "$archive"' EXIT
  curl -fL --retry 3 "https://codeload.github.com/longbridge/nsh/tar.gz/$revision" -o "$archive"
  actual=$(shasum -a 256 "$archive" | cut -d ' ' -f 1)
  [ "$actual" = "$checksum" ] || { echo 'NSH archive checksum mismatch' >&2; exit 1; }
  mkdir "$vendor/nsh"
  tar -xzf "$archive" -C "$vendor/nsh" --strip-components=1
  printf '%s\n' "$revision" > "$vendor/nsh/.financial-revision"
fi
[ "$(cat "$vendor/nsh/.financial-revision")" = "$revision" ] || { echo 'NSH revision mismatch' >&2; exit 1; }
patchfile="$root/native/patches/close-guard.patch"
if git -C "$vendor/nsh" apply --reverse --check "$patchfile" 2>/dev/null; then :
else git -C "$vendor/nsh" apply --check "$patchfile"; git -C "$vendor/nsh" apply "$patchfile"; fi
RUSTUP_TOOLCHAIN=stable cargo build --locked --manifest-path "$vendor/nsh/Cargo.toml" -p nsh-cli
printf 'NSH ready: %s\n' "$vendor/nsh/target/debug/nsh"
