# Consulta direta da OS pelo Cous — 16/10/2026

## Caminho de execução

`/diagnostico os 1141` (ou `/diagnostico 1141`) → Cous → `POST /v3/systemos/diagnosis` no runtime OpenTracy → `GET /api/v1/integracoes/cognicao/ordens/1141` no SystemOS → normalização temporal V4 → redação pelo pipeline existente → validação da conclusão no SystemOS → exibição no Cous.

O pedido contém somente o número ou UUID da OS. Não exige indexação da OS em `knowledge_documents`, identidade de captura ou entrada em `diagnosis_queue`. O SystemOS permanece a fonte dos registros técnicos. O pipeline ainda pode consultar sua base técnica e gravar traces de execução; consulta direta não significa ausência de rastreabilidade ou de dados nos traces.

A rota tradicional `/diagnostico <id de coleta>` continua disponível para as capturas do Cous. O fluxo administrativo existente de análise assistida não foi substituído por este comando: ele também pode conter rascunhos ainda não salvos, enquanto a consulta direta lê somente o estado salvo no SystemOS.

## Dados e limites

O exportador reutiliza `carregarContexto`, `prepararRascunhoAnalise`, `montarEvidenciasTecnicas`, o transporte temporal V4 e o contrato de redação existentes. Inclui inspeções, testes, checklist, serviços, registros de fechamento e medições. Correlações completas são processadas pelas regras V4; os arrays de frames não são enviados como prosa ao LLM. Coletas e marcadores vazios/inválidos conservam sua identidade. Fotos/PDFs são metadados, sem interpretação visual nesta integração.

O snapshot técnico tem teto explícito de 128 KB; a resposta completa, que também inclui projeções/prompt, tem teto de 512 KB no consumidor. O prompt narrativo possui teto conservador de 32.000 bytes. Esse teto não é uma contagem exata de tokens nem uma garantia para qualquer configuração de RAG. Não há corte silencioso para produzir uma conclusão aparentemente completa.

O cálculo V4 direto reutiliza o normalizador e o gerador de hipóteses do worker sem consultar uma captura persistida. Não acrescenta corroboradores do grafo às pontuações nessa etapa; essa limitação é devolvida no resultado. Pontuação heurística não é probabilidade calibrada nem certificação de conformidade.

## Validação e autorização

`COGNITIVE_READ_KEY` é uma credencial dedicada de consulta. Não reutiliza a chave TDMA de ingestão. `COGNITIVE_READ_ORGANIZATION_ID` fixa a organização permitida no servidor; não é aceito um escopo arbitrário enviado pelo cliente. Consulta por número e carregamento por UUID conferem a organização. Respostas têm `Cache-Control: no-store`.

O Linux usa `OPENTRACY_SYSTEMOS_URL`, `OPENTRACY_SYSTEMOS_READ_KEY` e `OPENTRACY_SYSTEMOS_ORGANIZATION_ID`. O endereço é configuração do servidor; o chamador não fornece URLs. Redirecionamentos HTTP são recusados. Valores privados ficam nos arquivos de ambiente, fora do Git.

O endpoint OpenTracy exige o token V3/knowledge, separado do token de chat do gateway. O Cous recebe ambos na composição de clientes.

Após gerar a redação, o OpenTracy chama `POST /api/v1/integracoes/cognicao/ordens/:id/validar`. Esse POST **somente valida**, sem salvar: recarrega a OS, compara o hash de conteúdo e aplica `validarAnaliseOpenTracy` e a composição de serviços sugeridos já existentes. Mudança de conteúdo durante a análise retorna conflito, sem aplicar uma conclusão antiga. Textos sem apoio continuam descartados, com indicação de resposta parcial.

O hash cobre o snapshot, o prompt e os serviços sugeridos; inclui também o estado da OS e os metadados de anexos usados na redação. A data da consulta não entra no hash.

Nenhum dos novos endpoints aprova serviços, altera estados, aplica conclusões ou fecha a OS.

## Modelo e operação

A rota ativa do OpenTracy usa `qwen3.5:4b` em `small` e `big`. O runtime acessa o Ollama do Windows pelo túnel Linux `127.0.0.1:11436`, com contexto 16.384 e timeout de 900 segundos. O timeout de leitura do Cous foi ajustado para 900 segundos na configuração local. O modelo efetivamente informado pelo estágio de roteamento acompanha o resultado.

É necessário reabrir o Cous que já estava em execução para carregar a configuração e o novo código. Windows/Ollama e túnel precisam permanecer disponíveis. As instruções de inicialização estão em `docs/INICIALIZACAO_TUNEL_OPENTRACY.md` no repositorio SystemOS.

## Verificações

- SystemOS: testes de credencial independente, escopo da consulta, identificador inválido, recusa de conclusão desatualizada e validação de referências; incluídos em `npm run test:unit`.
- OpenTracy: testes da rota com transporte HTTP simulado, autenticação, identidade de OS, contexto excessivo, consulta/validação na fonte e conflito por alteração da OS.
- Cous: cliente envia somente a identidade da OS e usa timeout de inferência; comando não envia ou diagnostica uma captura local.
- A validação real deve conferir que a OS e as contagens de documentos/capturas/fila permaneçam inalteradas. O resultado privado fica no estado local do OpenTracy, sem versionar dados de cliente.

### Ensaio real da OS 1141

A chamada foi feita pelo cliente Cous real, com credenciais separadas de chat e diagnóstico. A leitura retornou três séries e 42 frames; o prompt narrativo ocupou 10.661 bytes e a resposta de consulta completa 148.073 bytes. O estágio informou `qwen3.5:4b`; o Ollama confirmou execução no Windows por CPU, contexto 16.384 e sem alocação de GPU.

O pedido levou **443,32 segundos** (7 min 23 s), retornou conclusão validada de 1.783 caracteres e não teve parágrafos descartados. É uma medição deste equipamento/caso, não um prazo garantido. A OS permaneceu com o mesmo conteúdo e as contagens de `knowledge_documents`, `capture_sessions` e `diagnosis_queue` ficaram inalteradas.

Trace: `ff601f75-ec07-4aee-9d7f-bfcb84cfb517`. Resultado privado no Linux: `~/.local/state/opentracy-systemos/validacao-consulta-direta-1141.json`.

Verificações automatizadas: suíte geral SystemOS com 130 aprovados e quatro opcionais ignorados; os quatro testes específicos da consulta passaram após a ampliação do hash de origem. OpenTracy: 18 testes direcionados aprovados, incluindo a barreira temporal pela rota HTTP; Cous: 186 testes aprovados na suíte completa, com o teste do novo comando repetido após integrar o histórico local.
