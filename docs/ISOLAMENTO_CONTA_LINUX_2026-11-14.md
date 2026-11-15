# Dedicated OpenTracy account - staged Linux isolation

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
