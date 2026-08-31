# Integracao firmware, COUS, OpenTracy e DeepSeek

## Responsabilidades

- **Firmware:** mede, valida canais, calcula grandezas inferidas identificadas como tal e publica os contratos `electromechanical_observation_frame` v3 e `electromechanical_correlation_frame` v4.
- **COUS:** captura serial, valida o cabecalho da medicao, persiste localmente, atribui `event_id` estavel, sincroniza e resolve a identidade OS/numero de serie.
- **OpenTracy measurements:** armazena o evento bruto imutavel, valida tipo/versao e responde com recibo `accepted`, `rejected` e `duplicates`.
- **OpenTracy operational:** recebe a projecao normalizada da correlacao somente depois que a sessao de medicao e vinculada ao `capture_session_id` resolvido.
- **Diagnostico v3:** produz hipoteses e confianca por regras deterministicas, evidencias temporais e conhecimento consolidado.
- **DeepSeek:** consulta fatos por ferramentas somente leitura e explica o diagnostico. Nao recalcula medicoes nem altera a confianca formal.

## Fluxo canonico

```text
TMA_DATA
  -> validacao COUS
  -> POST /measurements/sessions/{id}/snapshots
  -> recibo de ingestao
  -> POST /v3/operational/resolve-capture
  -> POST /measurements/sessions/{id}/capture-link
  -> electromechanical_signatures + signature_deviations
  -> diagnosis_queue
  -> callback COUS
  -> narrativa DeepSeek baseada em tools
```

O COUS nao marca uma sessao como sincronizada se houver rejeicao ou se o recibo nao contabilizar todos os snapshots. Reenvios usam a mesma identidade e sao contabilizados como duplicados, sem nova persistencia.

## Camadas cognitivas

1. Medicao direta do firmware.
2. Qualidade e validade do canal/janela.
3. Grandeza inferida e fechamento fisico.
4. Persistencia temporal e modo de falha.
5. Corroboracao documental e historica.
6. Explicacao pelo DeepSeek.

As ferramentas `cous_facts` fornecem contagem/listagem de OS, medicao, diagnostico e evidencia de captura diretamente do PostgreSQL. Consultas quantitativas nao devem usar a quantidade limitada de documentos retornados pelo RAG.

## Entrada em operacao

1. Aplicar as migracoes de `knowledge/infrastructure/postgres/migrations` e `measurements/infrastructure/postgres/migrations`.
2. Reiniciar o runtime OpenTracy para recarregar o agente e o catalogo interno de ferramentas.
3. Reiniciar o COUS para carregar o cliente de sincronizacao atualizado.
4. Executar uma medicao de teste com OS e numero de serie validos.
5. Confirmar recibo sem rejeicoes, projecao vinculada e diagnostico com o mesmo `capture_session_id`.
