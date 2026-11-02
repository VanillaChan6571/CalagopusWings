#!/usr/bin/env bash

set -euo pipefail

calagopus_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
catwings_root="${CATWINGS_REPO:-/var/www/pterodactyl/CatWingsRepo}"

for required in git rg wc; do
    command -v "$required" >/dev/null 2>&1 || {
        printf 'Missing required command: %s\n' "$required" >&2
        exit 1
    }
done

[[ -d "$calagopus_root/.git" ]] || {
    printf 'Calagopus checkout is not a Git repository: %s\n' "$calagopus_root" >&2
    exit 1
}

[[ -d "$catwings_root/.git" ]] || {
    printf 'CatWings checkout is not a Git repository: %s\n' "$catwings_root" >&2
    exit 1
}

revision() {
    git -C "$1" log -1 --format='%H | %cI | %s'
}

calagopus_engine_revision() {
    git -C "$calagopus_root" log -1 --format='%H | %cI | %s' -- \
        application pbs-client Cargo.toml Cargo.lock
}

tracked_engine_files() {
    local root="$1"

    git -C "$root" ls-files -- . ':(exclude)comparison/**' | wc -l
}

source_lines() {
    local root="$1"
    local pattern="$2"

    (
        cd "$root"
        git ls-files -z "$pattern" | xargs -0 -r wc -l | tail -1 | awk '{print $1}'
    )
}

test_markers() {
    local root="$1"
    local language="$2"

    if [[ "$language" == rust ]]; then
        { rg -o '#\[(tokio::)?test\]' "$root" --glob '*.rs' || true; } | wc -l
    else
        { rg -o 'func Test[A-Za-z0-9_]+' "$root" --glob '*.go' || true; } | wc -l
    fi
}

signal_count() {
    local root="$1"
    local pattern="$2"
    local glob="$3"

    { rg -il "$pattern" "$root" --glob "$glob" || true; } | wc -l
}

printf 'CatWings revision:   %s\n' "$(revision "$catwings_root")"
printf 'Calagopus revision:  %s\n' "$(calagopus_engine_revision)"
printf '\n'
printf '%-12s %12s %14s %14s\n' Engine Source-lines Tracked-files Test-markers
printf '%-12s %12s %14s %14s\n' \
    CatWings \
    "$(source_lines "$catwings_root" '*.go')" \
    "$(tracked_engine_files "$catwings_root")" \
    "$(test_markers "$catwings_root" go)"
printf '%-12s %12s %14s %14s\n' \
    Calagopus \
    "$(source_lines "$calagopus_root" '*.rs')" \
    "$(tracked_engine_files "$calagopus_root")" \
    "$(test_markers "$calagopus_root" rust)"

printf '\nSource files containing feature signals (presence only):\n'
printf '%-16s %12s %12s\n' Signal CatWings Calagopus

for signal in revisions trash sqlite_query collab file_history seven_zip zip; do
    printf '%-16s %12s %12s\n' \
        "$signal" \
        "$(signal_count "$catwings_root" "$signal" '*.go')" \
        "$(signal_count "$calagopus_root/application/src" "$signal" '*.rs')"
done

