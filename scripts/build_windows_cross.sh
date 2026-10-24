#!/usr/bin/env bash
# Parse the complete build before executing it. A source edit made while a
# long-running compiler is active must not change the remaining shell commands.
set -euo pipefail

run_step() {
  local label="$1" started=$SECONDS
  shift
  printf '\n[Afterglow] %s\n' "$label"
  "$@"
  printf '[Afterglow] 完成 / Done (%ss)\n' "$((SECONDS - started))"
}

main() {
  local package_only=false
  case "${1:-}" in
    '') ;;
    --package-only) package_only=true ;;
    *) printf 'Usage: bash scripts/build_windows_cross.sh [--package-only]\n' >&2; return 2 ;;
  esac
  if (( $# > 1 )); then
    printf 'Usage: bash scripts/build_windows_cross.sh [--package-only]\n' >&2
    return 2
  fi
  cd "$(dirname "$0")/.."
  export RUSTUP_HOME="$PWD/开发缓存/工具链/rustup"
  # MSVC headers use case-sensitive aliases. WSL's Windows-mounted filesystem
  # cannot safely hold those symlinks; use a persistent Linux cache, not /tmp.
  build_cache="${AFTERGLOW_BUILD_CACHE:-$HOME/.cache/afterglow-desktop}"
  mkdir -p "$build_cache"
  export CARGO_HOME="${AFTERGLOW_CARGO_HOME:-$build_cache/cargo}"
  export CARGO_TARGET_DIR="$build_cache/windows-msvc-target"
  export XWIN_CACHE_DIR="$build_cache/xwin-cache"
  # cargo-xwin defaults to preparing both x86_64 and aarch64 SDKs even when
  # Cargo's --target is x86_64. This installer only needs the desktop x64 SDK.
  export XWIN_ARCH=x86_64
  export XWIN_VARIANT=desktop
  export LD_LIBRARY_PATH="$PWD/开发缓存/工具链/llvm/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export PATH="$PWD/开发缓存/工具链:$PWD/开发缓存/工具链/cargo/bin:$CARGO_HOME/bin:$PWD/开发缓存/工具链/llvm/usr/lib/llvm-18/bin:$PATH"

  if [[ "$package_only" == false ]]; then
    command -v cargo-xwin >/dev/null
    command -v clang-cl >/dev/null
    command -v lld-link >/dev/null
    command -v llvm-rc >/dev/null
    node scripts/version.mjs
    # Keep SDK setup separate and before the frontend build. cargo-xwin writes
    # xwin/DONE only after every SDK payload finishes; Ctrl-C before then leaves
    # an incomplete cache. Never fabricate that marker or delete partial downloads.
    printf '[Afterglow] 构建缓存 / Build cache: %s\n' "$build_cache"
    if [[ -f "$XWIN_CACHE_DIR/xwin/DONE" ]]; then
      printf '[Afterglow] 检查并复用 Windows SDK 缓存 / Checking cached Windows SDK\n'
    else
      printf '[Afterglow] 首次准备 Windows SDK 可能较慢；请等待完成以保存缓存。\n'
      printf '[Afterglow] Initial Windows SDK setup may take a while; let it finish to save the cache.\n'
    fi
    run_step '1/5 准备 Windows x64 SDK / Prepare Windows x64 SDK' cargo-xwin xwin cache xwin
    run_step '2/5 构建界面 / Build frontend' npm run build
    # custom-protocol embeds the built frontend so the EXE works without Vite.
    run_step '3/5 编译 Windows 程序 / Compile Windows app' \
      cargo-xwin xwin build --manifest-path src-tauri/Cargo.toml \
      --target x86_64-pc-windows-msvc --release --features custom-protocol
  else
    printf '[Afterglow] 仅打包现有编译产物 / Packaging existing build; skipping SDK and compilation.\n'
  fi

  local executable="$CARGO_TARGET_DIR/x86_64-pc-windows-msvc/release/afterglow-desktop.exe"
  if [[ ! -f "$executable" ]]; then
    printf '[Afterglow] 找不到编译产物，请先运行完整构建 / Run a full build first: %s\n' "$executable" >&2
    return 1
  fi
  run_step '4/5 组装程序文件 / Assemble app files' python3 scripts/package_portable.py \
    --exe "$CARGO_TARGET_DIR/x86_64-pc-windows-msvc/release/afterglow-desktop.exe"
  version="$(node --input-type=module -e 'import { readFileSync } from "node:fs"; import { desktopVersion } from "./scripts/version_metadata.mjs"; console.log(desktopVersion(JSON.parse(readFileSync("version.json", "utf8"))))')"
  run_step '5/5 生成官网风格安装包 / Build website-styled installer' python3 scripts/package_installer.py \
    --payload "$PWD/artifacts/Afterglow-$version-windows-x64-portable"
}

# Keep exit on the same parsed command line: do not read the script again after
# main returns, even if its source file was replaced during the build.
main "$@"; exit $?
