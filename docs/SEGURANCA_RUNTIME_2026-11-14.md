# Runtime security - 2026-11-14

Production activation requires OPENTRACY_RUNTIME_SECURITY=required and a private internal token (at least 32 characters). Unknown modes or missing/weak keys abort startup. The systemd drop-in pins required mode and NoNewPrivileges, UMask 0077 and no core dumps.

Administrative runtime routes and docs require an internal gateway credential or an operator Bearer. The Cous knowledge credential is accepted only for GET /agent/config. Knowledge, measurements, diagnosis, MCP, widget and public per-agent chat retain their existing authentication and contracts. This middleware does not replace protocol authentication.

Gateway upstream requests attach an internal credential only for the configured runtime origin. Incoming copies are replaced; external destinations never receive this header; runtime redirects are refused. No token is added to response headers. HTTP analysis concurrency is limited to two per process and excess receives 429/Retry-After. Status routes do not consume analysis slots. Cancellation and exceptions release slots. Diagnosis background worker concurrency/queue capacity are not changed by this limit.

Publish script requires pushed expected SHA, clean checkout, fast-forward ancestry, no active runtime/gateway connections and read-only idle diagnosis/callback checks. It privately backs up configuration, provisions an internal key locally, installs the versioned systemd drop-in and restarts runtime/gateway only. Cous/firmware stay running. Failure restores prior env/unit and Git revision, then restarts services; failed rollbacks must be investigated, never represented as passed. No data reset, SQL migration or financial operation is performed.

Pending: dedicated service accounts without Docker group; writable-path sandbox; PostgreSQL clients/firewall/roles review; background queue capacity and fuller protocol/dependency audit. NoNewPrivileges does not remove Docker socket access or isolate files of the shared user.

## Published verification

Production code was activated from d752004668c8c4a55f48215a223c8d2288e92eb3 after remote verification. Nine Node tests, 51 Python tests and TypeScript passed. Real Cous get_agent_config succeeded; its knowledge token was refused on runtime /policy. Gateway reads of agents/config/policy succeeded, and SystemOS API container read through VPS tunnel/gateway/runtime returned HTTP 200. Anonymous runtime administration returned 401. Queue and callbacks were idle before restarting; Cous and firmware were not restarted. No inference or customer data mutation was used for verification.

A temporary local dependency symlink was inadvertently included in the intermediate eda87dc commit, then removed in d752004 before deployment; no dependency artifact was installed from Git. History was preserved without force-push.

Next privileged inspection (read only): sudo python3 scripts/auditar-isolamento-host.py. It inventories database configuration/roles/origins and host socket/path permissions, without environment values, row data or any service/database changes. Administrative sudo is unavailable to the automatic SSH session. Do not migrate accounts or restrict PostgreSQL before reviewing these results.
