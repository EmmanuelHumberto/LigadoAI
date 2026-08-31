# Guia de Migração — COUS v2.0 → v3.1

> **Data:** 2026-06-22
> **Status:** Referência de implementação

---

## Visão Geral

O COUS v3.1 representa a transição de um sistema baseado em conceitos implícitos (v2.0) para um sistema com ontologia formal, Knowledge Graph operacional e sistema de confiança quantificável.

### O que muda

| Área | v2.0 | v3.1 |
|---|---|---|
| **Conhecimento** | "Casos Técnicos" como unidade máxima | KnowledgeUnits com 4 níveis e 6 tipos de relações |
| **Confiança** | Implícita, qualitativa | Formal: `C = 0.40·Eₑ + 0.25·Eₔ + 0.25·Eₕ + 0.10·Eᶜ` |
| **RAG** | Similaridade semântica pura | Scores compostos: semântico + documental + histórico + causal |
| **Diagnóstico** | Síncrono via chat | Assíncrono com fila, retry e callback |
| **Banco** | 2 tabelas (measurement_sessions, snapshots) | 29 tabelas em 6 camadas |
| **Schema** | Implícito nos payloads | Contratos JSON com `schema_version: "3.0"` |

### O que NÃO muda

- Firmware: compatibilidade binária mantida (payload legado aceito)
- API `/v1/*`: mantida sem alterações
- UI web: continua funcionando com `/v1/webhook`
- Cous terminal: comandos existentes preservados

---

## Migração do Banco de Dados

### Pré-requisitos

- PostgreSQL 15+
- Extensão `pgcrypto` habilitada
- Backup completo antes de aplicar

### Passos

```bash
# 1. Verificar migrations existentes
psql $DATABASE_URL -c "SELECT tablename FROM pg_tables WHERE schemaname='public'"

# 2. As migrations 006-010 são aplicadas automaticamente pelo lazy.py
#    ao iniciar o runtime com OPENTRACY_COUS_V3_DATABASE_URL configurada.

# 3. Verificar schema após migração
psql $DATABASE_URL -c "
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN (
  'domains', 'entities', 'instances', 'knowledge_units',
  'technical_cases', 'hypotheses', 'causal_chains'
)
ORDER BY table_name;
"
```

### Tabelas novas (29)

| Camada | Tabelas |
|---|---|
| Física | `domains`, `entities`, `instances`, `subsystems`, `electromechanical_profiles` |
| Operacional | `operational_sessions`, `capture_sessions`, `observations`, `snapshots`, `electromechanical_signatures`, `signature_deviations` |
| Documental | `knowledge_documents` (+3 colunas), `knowledge_chunks` (+1 coluna) |
| Epistêmica | `technical_cases`, `evidences`, `causal_chains`, `hypotheses`, `explanations` |
| Conhecimento | `knowledge_units`, `knowledge_unit_sources`, `knowledge_unit_relations`, `knowledge_contradictions` |
| Cognitiva | `cognitive_traces`, `trace_evidences`, `trace_documents`, `knowledge_feedback`, `goldens`, `diagnosis_queue`, `audit_log` |

---

## Migração de API

### Novos endpoints (todos em `/v3/`)

```
# KnowledgeUnits
POST   /v3/knowledge-units
GET    /v3/knowledge-units
GET    /v3/knowledge-units/{id}
PATCH  /v3/knowledge-units/{id}
POST   /v3/knowledge-units/{id}/promote
POST   /v3/knowledge-units/{id}/demote
GET    /v3/knowledge-units/{id}/relations
POST   /v3/knowledge-units/{id}/relations
DELETE /v3/knowledge-units/{id}/relations/{rid}
GET    /v3/knowledge-units/{id}/contradictions
POST   /v3/knowledge-units/{id}/contradictions

# Knowledge Graph
GET    /v3/knowledge-graph/{domain_id}
GET    /v3/knowledge-graph/{domain_id}/paths
GET    /v3/knowledge-graph/{domain_id}/validate
GET    /v3/knowledge-graph/{domain_id}/metrics

# Diagnóstico
POST   /v3/diagnosis
GET    /v3/diagnosis/{id}
GET    /v3/diagnosis/queue
```

### Contratos de payload

Toda comunicação entre componentes usa `schema_version: "3.0"`:

```json
// Firmware → Cous
{
  "schema_version": "3.0",
  "capture_session_id": "uuid",
  "instance": {"serial_number": "SN001"},
  "profile_label": "Faulhaber_1516SR_12V_v2",
  "signature": {...},
  "deviations": {...}
}

// Cous → OpenTracy
{
  "schema_version": "3.0",
  "correlation_id": "uuid",
  "operation": "diagnosis_request",
  "capture_session_id": "uuid",
  "evidence_set": [...],
  "callback_endpoint": "http://cous:8000/cous/diagnosis/callback"
}
```

---

## Configuração de Ambiente

Novas variáveis no `.env`:

```bash
# COUS v3 — Knowledge Units & Knowledge Graph
OPENTRACY_COUS_V3_ENABLED=1
OPENTRACY_COUS_V3_BACKEND=postgres
OPENTRACY_COUS_V3_DATABASE_URL=postgresql://user:pass@localhost:5432/opentracy
OPENTRACY_COUS_V3_AUTH_TOKEN=seu-token-aqui
```

Fallbacks automáticos:
- `OPENTRACY_COUS_V3_DATABASE_URL` → `OPENTRACY_KNOWLEDGE_DATABASE_URL`
- `OPENTRACY_COUS_V3_AUTH_TOKEN` → `OPENTRACY_KNOWLEDGE_AUTH_TOKEN`

---

## Rollback

Para reverter ao comportamento v2.0:

```bash
# Desabilitar features v3
export OPENTRACY_COUS_V3_ENABLED=0

# Reverter pipeline para cross_encoder (de composite)
# Editar agent/pipeline/rerank.yaml:
#   variant: cross_encoder

# OU manter v3 ativo — os endpoints /v1/* continuam funcionando
```

---

## Checklist de Migração

- [ ] Backup do PostgreSQL
- [ ] Configurar `OPENTRACY_COUS_V3_DATABASE_URL`
- [ ] Iniciar runtime (migrations automáticas)
- [ ] Verificar `GET /v3/status`
- [ ] Criar domínio via `POST /v3/knowledge-units`
- [ ] Atualizar `agent/pipeline/rerank.yaml` para `variant: composite`
- [ ] Testar diagnóstico: `POST /v3/diagnosis`
- [ ] Verificar `GET /v3/knowledge-graph/{domain_id}/validate`
- [ ] Monitorar métricas: `GET /v3/knowledge-graph/{domain_id}/metrics`

---

> **Próximo passo:** COUS v3.2 — Promoção automática de KU + Harness sobre KUs + Refinamento automático de pesos de confiança.
