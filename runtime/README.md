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

COUS v3 diagnosis runtime:

- `GET /v3/diagnosis/status` reports whether diagnosis is enabled, whether a
  database is configured, and whether the worker is running.
- `POST /v3/diagnosis` enqueues a diagnosis request in PostgreSQL.
- `GET /v3/diagnosis/{correlation_id}` returns queue status for one request.
- `POST /v3/diagnosis/{correlation_id}/retry` requeues a diagnosis that ended
  in `failed`.
- `GET /v3/diagnosis/queue` returns the recent diagnosis queue.
- `DiagnosisWorker` starts from the FastAPI lifespan when
  `OPENTRACY_DIAGNOSIS_WORKER_ENABLED=1` and a COUS v3 database URL is
  configured.
- The worker consumes `diagnosis_queue` and persists hypotheses/explanations
  before delivery. Callback delivery runs as a separate outbox with its own
  status, attempts, error and exponential backoff. An unavailable COUS callback
  therefore does not reclassify a completed diagnosis as failed.
- For `electromechanical_correlation_frame` v3 evidence, the worker treats
  firmware modes as physical hypotheses rather than reimplementing sensor
  thresholds. It validates known mode IDs, preserves persistence, current
  state, source channels and limitations, then correlates each mode with
  applicable Knowledge Units and causal chains.
- Unrelated Knowledge Units cannot replace a firmware mode. Documentary and
  historical evidence may corroborate the mode and increase formal confidence;
  without corroboration the result remains explicitly limited to physical
  telemetry.

## Vinculo com ordem de servico

`POST /v3/operational/resolve-capture` exige `service_order_number` e
`serial_number`. A OS deve existir como `knowledge_document` de tipo
`service_order`. O runtime compara a serie da medicao com
`metadata.extra.equipment_serial`; documentos indexados antes desse campo usam
transitoriamente a serie extraida do proprio texto.

A captura armazena o documento em `capture_sessions.service_order_document_id`
e as observacoes do cabecalho em `capture_sessions.header_observations`.
Observacoes entram no diagnostico como contexto relatado de baixa forca, nunca
como evidencia fisica independente.

Not mutated by the harness. Code releases only.
