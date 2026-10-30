#!/usr/bin/env bash

set -euo pipefail

calagopus_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
rust_image="${CALAGOPUS_RUST_IMAGE:-rust:1.99-bookworm}"

command -v docker >/dev/null 2>&1 || {
    printf 'Docker is required for the isolated build container.\n' >&2
    exit 1
}

printf 'Running the locked Calagopus suite in %s...\n' "$rust_image"

docker run --rm \
    --network bridge \
    --volume "$calagopus_root:/work" \
    --volume /root/.cargo/registry:/usr/local/cargo/registry \
    --volume /root/.cargo/git:/usr/local/cargo/git \
    --workdir /work \
    "$rust_image" \
    bash -c 'apt-get update -qq && apt-get install -y -qq cmake >/dev/null && cargo test --locked --workspace --no-fail-fast'

