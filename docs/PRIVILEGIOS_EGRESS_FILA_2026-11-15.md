# OpenTracy: database privileges, outbound connections and diagnosis capacity

Status: implemented and tested in source; production publication requires the root command and must not be inferred from tests alone.

## Findings established from the actual deployment

The runtime database role ligadoai was not superuser, CREATEROLE, replication or BYPASSRLS and had no memberships, but retained CREATEDB and owned all 43 application relations in public. No application SECURITY DEFINER functions were present. Only application database ligadoai and maintenance database postgres existed. The account's services had no outbound IP restriction. The diagnosis worker claimed five rows every poll and spawned untracked tasks, with no active-task limit. The configured timeout was not applied, callbacks retried indefinitely, caller-selected callback destinations were unconstrained, and admission had no queue capacity. All 56 recorded jobs were completed (36 callbacks delivered, 20 polling/not_required), so no backlog required repair.

## Code corrections

Admission and explicit retry share a PostgreSQL transaction advisory lock. Active pending/processing capacity defaults to 100; full queues return 429 with Retry-After, while an equivalent correlation retry returns its existing state even at capacity. The evidence list is capped at 200 and serialized request size at 160 KiB. Conflicting correlation reuse remains 409.

Workers default to two active diagnoses. Claims obey remaining local slots and the database-wide processing count under the same lock. Tasks are tracked and canceled/requeued on orderly shutdown; stale processing leases become explicit failed jobs requiring operator retry. Each diagnosis attempt applies the configured timeout. Callback attempts default to eight. Exhaustion remains inspectable as failed with its attempt count; it does not resend forever or disappear. Pool defaults are one minimum/four maximum connections per repository and 30-second commands.

Callbacks accept only http loopback 127.0.0.1 / ::1 on 8000 or 8010 with the exact /cous/diagnosis/callback path. localhost is pinned to 127.0.0.1. Credentials, queries, fragments, alternative services, remote hosts and redirects are refused. The three historical callback destinations remain supported. Adding another destination requires deliberate code/network review.

## Production database policy prepared

A new login role opentracy_runtime has DML (SELECT/INSERT/UPDATE/DELETE) and sequence usage in this application's public schema, including defaults for future objects created by the migration owner. It has no object ownership, role memberships, CREATEDB, CREATEROLE, replication or BYPASSRLS. CREATE on public is removed from PUBLIC and the application role; the owner remains able to perform migrations. Runtime credentials are generated privately and only placed in a new protected environment file. The existing ligadoai owner remains for current Cous/admin workflows but loses CREATEDB. No customer records or stored credentials are placed in Git.

Role settings cap sessions at 24, statement time at 30s, lock waits at 5s and idle transactions at 30s. The runtime's real sandbox pre-start validates role flags, zero ownership, schema CREATE denial, all required DML permissions, a zero-row UPDATE rolled back, rejected permanent CREATE TABLE and rejected SET ROLE ligadoai. PUBLIC connection/temp privileges and catalog metadata are not claimed to be eliminated; broader isolation of the existing Cous owner remains separate work.

## Production network policy prepared

A dedicated nftables output table targets only the ligado-opentracy UID. New outgoing TCP connections are allowed only to exact loopback addresses and ports 5432 (database), 8001 (runtime), 8000/8010 (approved callbacks), 11437 (existing private Ollama forward) and 13301 (new private SystemOS API forward). Established replies remain possible. Other users, input firewall rules and the PostgreSQL LAN guard remain untouched. External providers/downloads and direct Internet/LAN management access are intentionally blocked for this account; the existing Hugging Face offline/read-only dependency policy stays active.

The existing restricted VPS SSH key gains precisely permitopen=127.0.0.1:3001. It retains forced nologin, the existing 11434 destination and reverse-listen restriction. No sshd restart or new public listener is required. A tracked user-service drop-in adds local 127.0.0.1:13301 -> VPS 127.0.0.1:3001. Runtime SystemOS reads use http://127.0.0.1:13301/api/v1 with the existing scoped cognitive key. Authentication and organization checks are preserved; this changes transport, not authorization.

Production units require the persistent egress guard. Actual pre-start probes test blocked management sockets after host positive controls and TCP reachability of the private SystemOS forward. Publication also performs an authenticated read of existing OS 1156 once; future boots do not depend on that customer record. No analysis, payment or OS mutation is used as a probe.

## Publication and rollback

scripts/permitir-forward-systemos-vps.py records Git source, script hash and before/after authorized_keys hashes; its private backup preserves the previous file. scripts/publicar-recursos-opentracy.py verifies a clean pushed SHA, the currently isolated source marker, active units and idle queue. It stops gateway/runtime, preserves their units, updates immutable Git source and source-only links, keeps the SAME writable state directory, installs private credentials, tunnel drop-in and UID policy, then proves actual startup/authentication.

On failure, it restores original source links and units against the SAME state directory, removes the new guard/tunnel drop-in and restarts the previous isolated services. It never starts obsolete user services or copies older state over current writes. The database owner losing CREATEDB and the unused restricted role are retained as safe security improvements if service publication rolls back. Root-private receipts and logs record outcome. Reboot and a real inference remain independent validation steps.

## Validation completed before publication

117 focused Python tests passed, including timeout, exact callback restrictions, redirects, cancellation, capacity configuration, state paths and publication configuration safeguards. A real disposable PostgreSQL database verified 12 concurrent requests, three admission slots, idempotency at capacity, full-queue retry refusal, two workers respecting two global tasks, cancellation/requeue and callback exhaustion at eight attempts; the database was removed afterward. An isolated user/network namespace verified IPv4/IPv6 egress denial, blocked unexpected loopback services, allowed database loopback, preservation of unrelated UIDs and rollback. The host firewall was not changed by that test. Production role denial and UID policy probes run again during privileged publication; they remain pending until that result is observed.

## Primary references

- https://www.postgresql.org/docs/17/role-attributes.html
- https://www.postgresql.org/docs/17/ddl-priv.html
- https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html
- https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html

## VPS prerequisite applied, Linux activation pending

On 2026-11-15T05:26:09.076527+00:00, script revision 6955127c5f7cbb99c1054104ffb445fa40e7b4fd added only permitopen=127.0.0.1:3001 to the existing restricted ligadoassist SSH key. authorized_keys SHA256 changed from 6f6fcd6060d54670dcabf863f116592e99ab68900b68bd5406c3fdac34146bcb to 958ee848976bdfab91580bfa6ada4c57780b45f452eda14a0f6caaefa93ddf02. No sshd or production-tunnel restart occurred. The Git source and script hash were verified before execution and the private receipt/backups retained on the VPS.

A separate temporary local forward on 13311 verified the actual restricted key and the authenticated cognitive read of OS 1156 with HTTP 200, then closed. This proves the new SSH destination without opening a permanent local port yet. Linux database role changes, UID egress enforcement, production tunnel drop-in and new diagnosis limits have NOT yet been activated. The root publisher performs those actions only when the operator executes the exact pushed command.
