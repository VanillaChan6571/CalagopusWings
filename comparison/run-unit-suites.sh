#!/usr/bin/env bash

set -euo pipefail

calagopus_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
catwings_root="${CATWINGS_REPO:-/var/www/pterodactyl/CatWingsRepo}"
rust_toolchain="${CALAGOPUS_RUST_TOOLCHAIN:-1.99.0}"

for required in cargo cmake go rustup; do
    command -v "$required" >/dev/null 2>&1 || {
        printf 'Missing required command: %s\n' "$required" >&2
        exit 1
    }
done

[[ -d "$catwings_root/.git" ]] || {
    printf 'CatWings checkout is not a Git repository: %s\n' "$catwings_root" >&2
    exit 1
}

rustup run "$rust_toolchain" rustc --version >/dev/null 2>&1 || {
    printf 'Rust toolchain %s is not installed.\n' "$rust_toolchain" >&2
    printf 'Install it explicitly with: rustup toolchain install %s --profile minimal\n' "$rust_toolchain" >&2
    exit 1
}

printf 'Running CatWings Go tests...\n'
(
    cd "$catwings_root"
    go test ./...
)

printf '\nRunning Calagopus Wings Rust tests with %s...\n' "$rust_toolchain"
(
    cd "$calagopus_root"
    cargo "+$rust_toolchain" test --locked --workspace --no-fail-fast
)

