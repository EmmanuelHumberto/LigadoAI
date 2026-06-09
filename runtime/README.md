# runtime/

Reads `agent/` + `techniques/` and serves requests.

- `compiler/` — turns `agent.yaml` (+ `pipeline/`) into an executable pipeline graph.
  Validates each stage against the corresponding `techniques/*/schema.yaml`.
- `executor/` — runs the compiled pipeline on a single request; emits to `traces/raw/`.
- `guards/` — runtime invariants (schema checks, rate limits, budget caps).

Measurements runtime:

- `GET /measurements/status` reports whether the measurements vertical is
  enabled, which backend is active (`memory` or `postgres`), and whether DB/auth
  were configured.
- `POST /measurements/sessions` and related routes persist to PostgreSQL when
  `OPENTRACY_MEASUREMENTS_BACKEND=postgres` and a database URL is configured.

Not mutated by the harness. Code releases only.
