# Linux PostgreSQL LAN guard - 2026-11-14

Privileged inventory from the operator confirmed listen_addresses=*, SSL on and loopback-only HBA rules. No evidence of remote database authentication was established. The runtime role ligadoai has CREATEDB; postgres is administrative. Active clients in the inventory were loopback/socket only. Shared Docker-group service accounts remain a separate unresolved risk.

The proposed nftables table rejects TCP destination port 5432 on non-loopback interfaces, IPv4 and IPv6. Its accept policy leaves unrelated traffic and existing firewall tables unchanged. The persistent systemd unit starts before the discovered PostgreSQL instance units; it does not restart or alter PostgreSQL, HBA, roles or data. Existing registered table/unit/config is not overwritten.

Functional test executes only inside newly created user/network namespaces: two simulated hosts, real IPv4/IPv6 TCP listeners and positive controls before policy. Remote database TCP is refused after policy, loopback remains usable, another port stays reachable, deletion restores the original reachability. Host firewall is untouched by this test. This validates network behavior, not database authentication, production activation or persistence across an actual reboot.

The root installer verifies expected pushed Git SHA, exact script/source provenance, clean checkout and no external database clients. It writes root-owned rules/unit and a restricted receipt, preserves PostgreSQL PIDs and verifies local SQL SELECT 1. Failures roll back the newly created table/config. Run only the exact revision reviewed. Administrative execution by the operator is required; automatic SSH has no passwordless sudo.

After the operator applies it, verify refusal from the actual LAN and successful Cous/gateway/runtime paths. Separate service accounts, least-privilege database roles and larger isolation work are still pending. Do not remove CREATEDB or change HBA without mapping maintenance/development dependencies.
