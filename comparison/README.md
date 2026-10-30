# CatWings comparison lab

This directory is the isolated test area for comparing this Calagopus Wings
fork with NekoHosting's CatWings fork.

## Safety boundary

The default scripts only inspect source and run unit tests. They do not:

- start Wings, open a listener, or install a system service;
- connect to the NekoHosting panel;
- access a production Wings configuration or server volume;
- create, stop, or remove Docker containers; or
- send lifecycle, file, backup, or console requests to a node.

Any live API or Docker comparison must use two disposable nodes, disposable
server data, unique ports, and a dedicated Docker network. Production node
URLs, tokens, volumes, and `/var/lib/pterodactyl` are out of scope.

## Checkouts

- Calagopus fork: `/var/www/pterodactyl/CalagopusWingsRepo`
- CatWings fork: `/var/www/pterodactyl/CatWingsRepo`
- Calagopus upstream: `https://github.com/calagopus/wings`

The comparison branch is `codex/catwings-comparison-lab`. The fork's `main`
branch stays aligned with upstream.

## Baseline commands

```bash
./comparison/source-report.sh
./comparison/run-unit-suites.sh
./comparison/run-calagopus-container.sh
```

`source-report.sh` records revisions, repository size, test markers, and source
signals for the features Neko Panel cares about. Signals show that relevant
code exists; they are not proof that behavior is correct or API compatible.

`run-unit-suites.sh` runs CatWings' Go suite and Calagopus Wings' locked Rust
workspace suite. Calagopus currently requires Rust 1.99.0, so the script uses
that explicit toolchain without changing the machine's default Rust version.
It also needs native build tools such as CMake. When those should not be
installed on the host, `run-calagopus-container.sh` runs the same locked suite
in a disposable Rust build container. It does not mount the Docker socket,
Wings configuration, or game-server data.

## Fair comparison plan

1. **Source and unit baseline** — establish build health and feature presence.
2. **API contract suite** — send identical authenticated requests to two
   disposable nodes and normalize responses before diffing them.
3. **File workload** — compare upload, listing, ZIP create/extract, large-file
   range reads, traversal rejection, revisions, trash, and SQLite queries.
4. **Server workload** — compare console streaming, start/stop/restart, resource
   telemetry, crash recovery, schedules, and installation behavior.
5. **Backup workload** — compare create, restore, checksum integrity, exclusion
   rules, cancellation, and interrupted-operation recovery.
6. **Soak and fault tests** — measure daemon RSS/CPU, response latency, dropped
   WebSockets, restart recovery, and behavior when Docker or the panel is
   temporarily unavailable.

Each stateful case must create its own fixture, verify the result, and remove
only that fixture. No benchmark result should be used for a migration decision
unless both engines run on the same host, storage, Docker version, image, Java
workload, and resource limits.

## Decision criteria

Performance is only one input. The recommended engine must also satisfy:

- compatibility with NekoHosting's control-plane contract;
- scoped authentication and least-privilege behavior;
- reliable console and lifecycle operations;
- safe file paths, archives, restores, and interrupted-operation recovery;
- maintainable upstream synchronization; and
- an acceptable rollback path for existing CatWings nodes.

