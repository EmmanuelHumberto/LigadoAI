# Gateway security - 2026-11-14

Scope: SystemOS gateway on Linux. Runtime diagnosis and measurements contracts unchanged.

- Bind Node gateway to 127.0.0.1; VPS reverse SSH tunnel and local Cous continue using loopback.
- Reject requests when operator credentials are absent; abort server startup without BACKEND_API_KEYS. No implicit anonymous development mode.
- Compare presented operator keys using timingSafeEqual; preserve rotation with comma-separated keys.
- Read cognitive bodies incrementally, maximum 160 KiB, including chunked input. Cancel oversized or stalled reads; deadline 10 seconds. Upstream timeout remains unchanged.
- Tests exercise absent/wrong/valid/rotated keys, byte boundary, Unicode, oversized declaration, streaming cancellation, timeout and canonical cognitive proxy. TypeScript typecheck passed.

Deployment: commit and push first; verify remote SHA, fast-forward clean source checkout, retain root-private backup/receipt, restart only gateway after checking active connections. Verify loopback listener, LAN refusal, anonymous denial and authenticated read-only control through VPS. Do not restart Python diagnosis runtime or Cous.

Pending: separate service account without Docker privileges; sandbox; administrative runtime authentication preserving internal consumers; inventory/restrict PostgreSQL; concurrency/rate limits. These changes do not provide full Linux isolation or complete the security audit.
