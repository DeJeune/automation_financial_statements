#!/bin/sh
# Pinned standalone Biome: development tooling, never bundled in the application.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
version=2.6.2
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) asset=biome-darwin-arm64; checksum=be66b76dcb930b1e365bd36c4f5d8557c2dda70b31567f8bd15509e487753a69 ;;
  Darwin-x86_64) asset=biome-darwin-x64; checksum=9bba9be8c50bf2a58bc6de8023b599e57613588800bd843273e9ccaa4deba52c ;;
  Linux-x86_64) asset=biome-linux-x64; checksum=43c08f3454d375d38c6441939acc8a557702bc8459272dd513f4f7474a4ed352 ;;
  *) echo 'Use scripts/biome.ps1 on Windows; this platform is not configured.' >&2; exit 1 ;;
esac
cache="$root/native/.tools"
exe="$cache/biome-$version-$asset"
mkdir -p "$cache"
if [ ! -f "$exe" ]; then
  download=$(mktemp "$cache/biome-download.XXXXXX")
  trap 'rm -f "$download"' EXIT
  curl -fL --retry 3 "https://github.com/biomejs/biome/releases/download/%40biomejs/biome%40$version/$asset" -o "$download"
  actual=$(shasum -a 256 "$download" | cut -d ' ' -f 1)
  [ "$actual" = "$checksum" ] || { echo 'Biome checksum mismatch' >&2; exit 1; }
  chmod +x "$download"
  mv "$download" "$exe"
fi
actual=$(shasum -a 256 "$exe" | cut -d ' ' -f 1)
[ "$actual" = "$checksum" ] || { echo 'Biome checksum mismatch' >&2; exit 1; }
cd "$root"
exec "$exe" "$@"
