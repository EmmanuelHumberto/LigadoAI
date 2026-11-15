# Disponibilidade do runtime durante a inferência

## Evidência

Na análise bem-sucedida da OS 1159 (15/11/2026, 11h51–11h54 America/Sao_Paulo), a rota async /run chamou diretamente PipelineExecutor.run, síncrono, incluindo a espera pelo Ollama. Durante essa espera, /health e leituras de conhecimento excederam 5–15 segundos. Depois da conclusão voltaram a responder normalmente.

## Correção preparada

- /run despacha todo o trabalho síncrono (checagem/consumo de quota, pipeline e gravação de trace) para um worker dedicado. O contrato da resposta, autorização, sessão/histórico e timeout Ollama permanecem os mesmos.
- Capacidade total de duas tarefas: uma executando e uma aguardando. Excesso retorna 429 com Retry-After 5; não há fila ilimitada nem crescimento ilimitado de threads.
- ContextVars são copiados por requisição, preservando tenant/agente para caminhos, credenciais, quotas e traces.
- Cancelamento remove trabalho que ainda aguarda; trabalho já em execução conserva a capacidade até terminar de verdade. Erros também liberam a capacidade. Não há promessa de interromper uma chamada síncrona em execução.
- PipelineExecutor, compartilhado com canais síncronos API/widget, agora serializa chamadas ao mesmo objeto. Isso evita sobrepor instâncias de técnicas/modelos que eram declaradas thread-unsafe.
- Publicação parte da revisão ativa 1831c2f, preserva role restrita/firewall/túnel/estado/limites de diagnóstico. O publicador exige ausência de solicitações ativas e testa uma inferência real sintética junto com leituras autenticadas; em falha aguarda o trabalho aceito antes de reverter. Uma rodada sintética gera um trace de teste sem dados de cliente, sem operações financeiras.

## Validação

Teste ASGI mantém uma inferência síncrona intencionalmente bloqueada e prova saúde 200, conhecimento autenticado 200, anônimo 401 e retorno original da análise. Outros testes verificam identidade isolada, capacidade, cancelamento pendente/ativo, recuperação após erro e serialização com chamadores síncronos.

171 testes passaram; um teste hosted pré-existente continua marcado como skip. Publicação privilegiada e verificação de inferência real ainda pendentes.

Escopo: resolve a espera síncrona da rota /run. Não converte todas as outras rotas de CPU/IO pesado do produto em jobs; elas devem ser avaliadas separadamente quando usadas. O worker dedicado é por processo; a implantação atual usa um processo runtime.
