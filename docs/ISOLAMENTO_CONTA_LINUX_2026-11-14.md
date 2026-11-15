# Dedicated OpenTracy account - active Linux isolation

Runtime and gateway form one application and share agent/channel state. The host boundary uses one exclusive system account, ligado-opentracy, with no Docker/sudo membership and no interactive login. It does not separate gateway from runtime within this application. The SSH tunnel remains under its existing account; application processes cannot read its credentials.

The disk has approximately 3.3 GiB free. Python dependencies occupy 5.2 GiB and are reused via selected read-only systemd bind mounts; Node dependencies and Hugging Face hub artifacts are read-only too. The Hugging Face token directory is not mounted. Startup still depends on these original dependency directories until later managed relocation. Other personal directories are inaccessible. Nothing is deleted from the original installation.

## Preparation is not cutover

scripts/preparar-conta-opentracy.py requires root and a pushed expected SHA. It creates the dedicated account, extracts immutable code from Git archive, snapshots state and privately prepares configuration. It starts candidate runtime/gateway on loopback 18011/18012 with memory repositories, no production database/provider credentials and disabled diagnosis worker. Existing services, ports, tunnel and Cous stay active. Candidates are stopped and temporary units removed after verification. READY_NOT_ACTIVATED does not mean the live application has migrated.

The sandbox applies ProtectSystem=strict, ProtectHome, private tmp/devices, no capabilities, NoNewPrivileges, namespace restrictions and explicit writable state/cache/home. A pre-start process inside the actual sandbox proves personal-file/Docker denial, denied source/dependency writes, allowed state writes, UID/group restrictions and canonical storage-code imports. Root execution is needed to prove these properties; syntax tests alone are insufficient.

## Source recovery

Legacy ledger/corpora anchors pointed into ignored tenant state. Ten Python source/test files matched their pre-anchor Git history byte-for-byte and are recovered under storage_packages. Only ledger's state anchor was adapted to OPENTRACY_STATE_ROOT. No customer records are versioned. Current user services retain original import behavior until explicit cutover; isolated execution prioritizes canonical packages in PYTHONPATH with a distinct writable working directory. Runtime state is separate from immutable source.

State manifests preserve Python documents and the legitimate relative dataset version pointer, excluding only recovered implementation modules and derived bytecode. Unexpected or escaping links are refused. Source before/after hashes and copy hashes must agree; concurrent changes defer preparation. Configuration duplicates with conflicting values are rejected instead of silently changing credentials.

## Validation and next stage

Unit syntax is verified with systemd-analyze. Source-import, manifest/link/configuration tests and existing runtime/diagnosis/corpus tests use canonical package paths. The root candidate test remains pending until executed by the operator. No production database, role, HBA or firewall change is performed by preparation.

After root proof, prepare a reviewed cutover with a fresh state snapshot, idle queue checks, real authenticated database/integration tests, disabled legacy writers and rollback preserving new writes. Do not activate the stale preparation snapshot. Activation is not implemented or claimed by this preparation script. Dedicated per-component identities, CREATEDB review, tighter egress and background queue limits remain follow-up work. No Drive synchronization is authorized here.

## Candidate failure identified on November 15

The first privileged preparation started both isolated candidates and passed sandbox pre-start checks, but GET /agent/config returned 500: its resolved prompt path was under writable state while serialization computed a path relative to immutable source. Production services were not switched. Prompt paths now use a stable agent-relative API path for reads and edits, validating containment before reading; sibling-prefix and symlink escapes are rejected. Regression tests call the configuration endpoint with both colocated and separated state. A new privileged preparation is still required; this code correction is not production cutover.

## Privileged candidate proof completed

Operator output saved on the Linux desktop confirms READY_NOT_ACTIVATED at 2026-11-15T03:48:38.198196+00:00 (00:48 Sao Paulo) for ff858d329c66049f97186f29ef621de12329e3ca. Both candidate components ran as UID 997 with no Docker group, Docker socket and personal-file access denied, source/dependency writes denied, state writes allowed, NoNewPrivileges and no effective capabilities. Canonical storage source loaded from the release. Both health checks returned 200 and 644 state files were verified. Candidates received no production database credentials. Existing production services were unchanged and remain active. This verifies the candidate sandbox, not production cutover, database integration or inference under the new account.

Next cutover must quiesce legacy writers, recheck the diagnosis queue, take a fresh state snapshot and retain rollback that preserves writes. Do not start production using the older candidate snapshot. The dedicated-account migration is still pending.

## Production activation procedure prepared

scripts/ativar-conta-opentracy.py accepts an exact pushed publisher commit and requires the successful ff858d3 candidate proof. It refuses unrelated source changes since that tested release. The running source remains ff858d329c66049f97186f29ef621de12329e3ca; publisher and source commits are recorded separately. Preparation snapshots are replaced with fresh verified state only after both legacy writers stop and the diagnosis queue is idle. Original data remains intact. No Cous, firmware, payment or Drive operation is performed.

The new runtime starts with diagnosis workers disabled, real credentials, the same validated sandbox and an additional database SELECT in a read-only transaction inside that sandbox. Authenticated and anonymous-access checks run before handover; the real gateway is first verified on a closed-to-clients loopback test port 18012. Before production ingress and workers reopen, the root-owned handover marker is committed, old user services are disabled and conditionally inhibited, and system-level units are enabled. Environment updates are atomic.

Failures before handover stop the new services and restart the unchanged legacy services. Failures after handover preserve isolated state and report HANDOVER_COMMITTED_NEEDS_ATTENTION; they never restart stale legacy writers. The root-private activation directory retains the fresh-state manifest, result and diagnostic journal. A post-handover fault needs operator diagnosis and forward recovery of the isolated units, not a blind legacy restart. Configuration, files and database credentials are not printed. This procedure is prepared, not yet activated. Reboot and a real inference remain independent validation steps.

## First activation attempt and correction

Publisher 263b576 rolled back before handover. Its real runtime passed isolation, read-only database access, startup and authenticated configuration checks; the gateway pre-start probe rejected an omitted OPENTRACY_STATE_ROOT in its restricted environment. The original services were restored and both health endpoints returned 200. No handover marker was committed. The corrected publisher builds the gateway environment with explicit state and agent paths, still excluding database/provider credentials; its regression test imports the actual canonical ledger module in a subprocess with that environment. The original strict pre-start assertion is preserved. A fresh activation attempt remains necessary; this is not evidence of production migration.

## Gateway authorization contract correction

Publisher 89d438b rolled back before handover because its verification incorrectly expected the Cous knowledge token to access gateway /v1/agent/config. The real Cous client reads runtime /agent/config directly; the runtime intentionally permits that scoped read, while gateway /v1 administration accepts BACKEND_API_KEYS only. No gateway permission is broadened. The publisher now requires anonymous=401, operator=200 and knowledge=401 on the gateway, plus the existing runtime knowledge=200 and policy knowledge=401 checks. Regression cases reject each inverted permission result. Runtime/gateway legacy services remain healthy after rollback. A new root activation remains pending.

## Production activation verified — November 15, 2026

The operator's saved administrative result confirms ACTIVATED at 2026-11-15T04:55:37.616543+00:00 (01:55:37 Sao Paulo). Source is ff858d329c66049f97186f29ef621de12329e3ca and publisher is afb14357d732b8ffd9ca36bd67c4b74d219173c2. These identifiers intentionally differ: the publisher activates the previously proven immutable source and records its own version separately. Fresh state contained 644 verified files; the queue had zero active requests and zero processing callbacks before cutover.

Independent post-activation checks confirmed system units ligado-opentracy-runtime and ligado-opentracy-gateway active/enabled under ligado-opentracy, with ProtectSystem=strict, ProtectHome=yes, NoNewPrivileges=yes and empty CapabilityBoundingSet. Legacy user services are inactive/disabled with MainPID=0. The unchanged user SSH tunnel remains active. The public root-owned marker points at the source above. Only loopback 8001/8002 listen; the temporary gateway test port 18012 is closed. Anonymous configuration reads return 401; both health endpoints return 200.

The real SystemOS API container in the VPS completed its authenticated gateway-to-runtime configuration read with HTTP 200. The actual Cous client, using its existing config/token provider, read runtime configuration successfully and reported backend/runtime health true. Neither Cous nor firmware was restarted; no real inference, financial operation or Drive synchronization was executed. The main security boundary is now active in production.

Still not proven: behavior after a host reboot and a real customer-requested inference under this account. Dependencies remain read-only binds from the previous installation, runtime and gateway intentionally share one application account, and broader database role/egress/background-queue review remains separate follow-up work. Do not restart legacy writers against their preserved pre-cutover state.
