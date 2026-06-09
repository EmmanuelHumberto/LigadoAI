# OpenTracy

Self-improving AI agent harness. You ship a default agent; it learns from real
usage, proposes its own improvements, and routes them through evals + human
approval before they go live.

> **Status:** experimental. APIs and the agent DSL move week-to-week. Don't pin
> to a tag yet.

## What it gives you

- A trainable agent surface at `agent/` — one YAML + a handful of Python files.
  Mutated by Claude Code (driven by the harness) in response to evidence from
  real traces.
- A default agent implementation already wired with DeepSeek routing:
  `deepseek-chat` as the small model and `deepseek-reasoner` as the escalation
  path for harder requests.
- An **autonomous engineering loop** modeled on Lin et al.'s AHE algorithm
  (arxiv 2604.25850). The harness proposes candidate edits, critiques them,
  runs evals, and applies the winners as file-level patches with cheap rollback.
  Each edit is a falsifiable change with a per-change KEEP / IMPROVE /
  ROLLBACK_AND_PIVOT verdict, inline semantic verification of rollout responses,
  optional best-of-N exploration, and a long-term memory tier.
- A typed runtime that compiles `agent/` into an executable pipeline and serves
  requests over HTTP, MCP, **Slack** (Socket Mode — no public URL needed), an
  **opt-in WhatsApp** channel (see [docs/channels/whatsapp.md](docs/channels/whatsapp.md)),
  and an embeddable web widget. Every trace records the channel it came from.
- A guided onboarding that names the agent with a short, stable id, and a trace
  view that renders agent messages as Markdown.
- An eval suite with goldens, regression detection, and per-trace attribution
  so you can see *why* a proposed change is better (or worse).

## Quick start

### Requirements

- **Python 3.11+** and [**uv**](https://docs.astral.sh/uv/)
- **Node 20+** (ships `npm`)
- An **Anthropic API key**

### Setup

```bash
git clone https://github.com/OpenTracy/OpenTracy
cd OpenTracy
cp .env.example .env     # then set ANTHROPIC_API_KEY
make install             # Python (uv) + backend + UI dependencies
```

`make install` runs `uv sync --extra rag` (the default agent's retrieval stage
needs it) and `npm install` in `backend/` and `ui/`. For tests/linting use
`make install-dev`.

### Run

Start everything in the background:

```bash
make up      # runtime :8001, backend :8002, ui :5174 — logs in .run/
make down    # stop all three
```

…or run each in its own terminal:

```bash
make runtime    # runtime API   → http://localhost:8001
make backend    # gateway       → http://localhost:8002
make ui         # web UI        → http://localhost:5174
```

Then open <http://localhost:5174>. The shell boots straight to Evolution — no
login, no signup. OSS runs single-tenant on localhost by design.

> Prefer raw commands? `make help` lists every target; each just wraps the
> obvious `uv run` / `npm run` invocation.

### Configuration

- **`ANTHROPIC_API_KEY`** is the only required variable. See
  [`.env.example`](.env.example) for the rest.
- **Ports** default to `8001` (runtime), `8002` (backend), `5174` (UI). Override
  them in `.env` with `OPENTRACY_RUNTIME_PORT` / `OPENTRACY_BACKEND_PORT` /
  `OPENTRACY_UI_PORT`; `make` wires the services together accordingly.
- **WhatsApp** is **off by default**. To enable it, install the optional
  dependency (`cd backend && npm install baileys`) and run the gateway with the
  flag:

  ```bash
  make backend WHATSAPP=1      # sets OPENTRACY_ENABLE_BAILEYS=1
  ```

  Baileys is GPLv3 and an unofficial WhatsApp Web client — read
  [docs/channels/whatsapp.md](docs/channels/whatsapp.md) before enabling.
- **ClickHouse** is optional. The `.env.example` enables it; set
  `OPENTRACY_CH_ENABLED=false` to use the local store instead.
- **Measurements** default to in-memory storage. To persist `/measurements/*`
  in PostgreSQL, set `OPENTRACY_MEASUREMENTS_BACKEND=postgres` and either
  `OPENTRACY_MEASUREMENTS_DATABASE_URL` or `OPENTRACY_KNOWLEDGE_DATABASE_URL`.
  The runtime exposes `GET /measurements/status` so clients can verify
  `backend`, `database_configured` and `auth_configured`.
  Session creation now validates the measurement header before persistence and
  rejects invalid payloads with HTTP `422`.

### Measurements runtime notes

- `POST /measurements/sessions` validates:
  - `tipo_coleta` obrigatório;
  - `peca_substituida` obrigatória em `reparo` e `pos-reparo`;
  - pelo menos uma vertical em `verticais`;
  - `baudrate > 0`;
  - `duracao_seg > 0`;
  - `curso_nominal_mm` dentro do intervalo `[curso_min_mm, curso_max_mm]` quando os três campos existem.
- `POST /measurements/sessions/{id}/snapshots` mantém snapshots inválidos como
  registros com `status=invalid`, preservando evidência para diagnóstico.
- O runtime de medições lê o ambiente depois do `.env`; por isso
  `GET /measurements/status` reflete o backend real configurado no processo.

### Measurements quick use

Configuração mínima para PostgreSQL no `.env`:

```dotenv
OPENTRACY_MEASUREMENTS_BACKEND=postgres
OPENTRACY_MEASUREMENTS_DATABASE_URL=postgresql://ligadoai:ligadoai@localhost:5432/ligadoai
OPENTRACY_MEASUREMENTS_AUTH_TOKEN=seu-token-aqui
```

Exemplos de uso:

```bash
curl -H "Authorization: Bearer $OPENTRACY_MEASUREMENTS_AUTH_TOKEN" \
  http://localhost:8001/measurements/status

curl -X POST \
  -H "Authorization: Bearer $OPENTRACY_MEASUREMENTS_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8001/measurements/sessions \
  -d '{
    "header": {
      "fabricante": "DKLAB",
      "modelo": "W1PRO",
      "tipo_coleta": "desempenho",
      "verticais": ["hall", "power"]
    }
  }'
```

Fluxo esperado:

1. criar a sessão em `/measurements/sessions`;
2. enviar snapshots em `/measurements/sessions/{id}/snapshots`;
3. gerar diagnóstico em `/measurements/sessions/{id}/diagnose`;
4. gerar laudo em `/measurements/sessions/{id}/report`.

### Known gaps

The core runtime is in place, but a few surfaces are still intentionally stubbed or phase-gated:

- Slack OAuth callback automation is not implemented; OSS uses the manual manifest + token flow.
- Some hosted/multi-tenant flows stay behind `OPENTRACY_MULTI_TENANT=1`.

Those are the remaining implementation gaps to close when you move beyond the current OSS baseline.

## Architecture

| Directory | Role |
|---|---|
| `agent/` | The trainable surface. YAML + Python. Mutated by the harness. |
| `techniques/` | Catalog of layer types (RAG, reranking, routing). Read-only. |
| `runtime/` | Compiles `agent/` into a pipeline and serves requests. |
| `evals/` | The loss function. Goldens, suites, runners, attribution. |
| `experiments/` | Candidate configs + results. The training workspace. |
| `harness/` | The optimizer: proposer, critics, approver, executor, rollback. |
| `ml/` | Models trained on accumulated data. |
| `ledger/` | Append-only audit trail. |
| `traces/` | Runtime accumulator (conversations, labels, pins). |
| `corpora/` | Knowledge accumulator (RAG content with usage stats). |
| `policies/` | Human-set rules for the harness. |
| `backend/` | Request-serving layer (API, channels). |
| `connectors/` | Outbound integrations. |
| `ui/` | Frontend (React + Vite + TS). |

The loop:

```
traces/  →  evals/  →  harness/proposer/  →  harness/critics/
                              ↓
                     harness/synthesizer/  ↔  experiments/candidates/
                              ↓                     (iterate)
                     harness/approver/   →   agent/ (live)   →   traces/
```

The harness mutates `agent/`, appends to `traces/` and `ledger/` via API, and
ingests into `corpora/`. Everything else is framework. See
`config/claude_code.yaml` for the authoritative allowlist.

Languages: Python (`harness/`, `runtime/`, `evals/`, `ml/`, `techniques/`),
TypeScript (`backend/`, `ui/`).

## Default agent

The repository already ships a first concrete agent implementation in `agent/`.

- `agent/pipeline/route.yaml` uses the `small_first` routing strategy.
- The current small model is `deepseek-chat`.
- The current escalation model is `deepseek-reasoner`.
- `escalate_on_failure: true` promotes harder or low-confidence requests to the
  reasoning path automatically.

That means DeepSeek is not just a future integration here; it is the active
baseline agent configuration committed in the repository.

## Distribution modes

| Mode | When | What's different |
|---|---|---|
| **OSS local** *(default)* | Clone, run for yourself or a single team. | Single-tenant. No login. Everything at the project root. |
| **Hosted/multi-tenant** | A managed deploy serving multiple orgs. Enable via `OPENTRACY_MULTI_TENANT=1`. | Per-tenant namespacing under `tenants/<id>/…`, Firebase-backed login, per-tenant Bearer tokens, KMS-encrypted BYOK keys. Requires the private `opentracy-infra` sibling repo. |

Hosted-only code is gated behind the env flag and adds zero overhead when off.

## Configuration

See [`.env.example`](.env.example) for the full list. The minimum to get
running is `ANTHROPIC_API_KEY`.

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
