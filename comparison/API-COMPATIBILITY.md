# API compatibility checkpoint

Recorded against:

- CatWings `7377117b9b476d5a25c58bc22d1d3d71c221029f`
- Calagopus Wings `28657dbc625ac1f4f69d039805518f4594b6d3a3`

## Confirmed common read-only routes

Both engines expose authenticated `GET /api/system` and `GET /api/servers`.
Both use an inbound `Authorization: Bearer <node-token>` header. The node token
secret—not the panel-facing `token_id.token` pair—is the inbound credential.

Missing or invalid authentication is rejected by both engines, but status codes
differ:

- CatWings returns 401 for a missing/malformed header and 403 for a bad token.
- Calagopus returns 401 for both cases.

Clients should treat both 401 and 403 as authentication failure during a
migration. The comparison harness accepts either while still recording the
observed status.

## System v2 response mismatch

CatWings explicitly checks `?v=2` and returns a nested response containing
`version`, `docker`, and `system`. Its `system` object includes architecture,
CPU thread count, memory, kernel, OS, and OS type; its `docker` object includes
runtime, cgroup, container, storage, and runc information.

Current Calagopus source does not branch on the `v` query parameter for this
route. It returns the flat legacy-style fields `architecture`, `cpu_count`,
`kernel_version`, `os`, and `version`, plus a Calagopus-specific `bandwidth`
object.

Therefore `/api/system?v=2` is not response-shape compatible at these revisions.
This matters to NekoHosting because a client expecting CatWings' nested v2
payload cannot obtain Docker, memory, or nested system fields from the current
Calagopus response. The black-box contract probe treats this as incompatible
even if both requests return HTTP 200.

## Broader Calagopus surface

Calagopus has many routes beyond the Pterodactyl/CatWings baseline, including
file revisions, trash, SQLite queries, collaborative permissions, system stats,
logs, backup inspection, Restic management, ports, and upgrade operations.
Those additions are candidates for Neko Panel features, but each needs explicit
authorization, path-safety, concurrency, cancellation, and recovery testing.

## Required canary evidence

Before selecting Calagopus, run the read-only probe against identical disposable
nodes and then implement the stateful fixture suite. A replacement decision
requires:

1. common route request and response compatibility;
2. NekoHosting authentication compatibility;
3. deterministic cleanup after file, archive, backup, and lifecycle cases;
4. console/WebSocket correctness under reconnect and token revocation;
5. resource and latency measurements under the same workload; and
6. recovery evidence after daemon, Docker, disk, and panel interruptions.
