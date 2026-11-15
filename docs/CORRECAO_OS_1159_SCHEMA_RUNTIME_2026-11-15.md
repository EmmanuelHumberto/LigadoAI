# OS 1159 — inicialização do conhecimento com privilégio mínimo

## Causa comprovada

Depois da publicação de `7b5516d56169020cb6b5d9003a23221cfda4dedf`, o GET autenticado de um job de conhecimento existente retornou HTTP 500. Os adaptadores lazy de conhecimento e medições executavam todos os arquivos de migração no primeiro acesso. A credencial `opentracy_runtime`, corretamente sem DDL/ownership, recusou essa operação. A validação anterior de conexão/fila e leitura de configuração não cobria essa inicialização. Os logs do SystemOS registraram duas análises da OS 1159 como BadGatewayException/502; o vínculo cognitivo não chegou a receber job de indexação.

## Correção

- Inicialização lazy faz somente SELECT com LIMIT 0 em transação somente leitura, validando tabelas e colunas usadas. Não executa migrações nem ignora erros de esquema.
- Pool é fechado se a inicialização falha ou é cancelada; uma nova tentativa continua possível.
- Migrações passam a ter entrada administrativa explícita `scripts/migrate-postgres.py`, com DSN independente `OPENTRACY_MIGRATION_DATABASE_URL`, transação, lock e ledger de hashes. Nenhum serviço chama essa entrada. Instalações existentes exigem verificação do esquema antes do baseline explícito; não se deve reaplicar migrações antigas em produção. O ledger não é gravável pelo runtime.
- ExecStartPre passa a inicializar os dois adaptadores reais e realizar consultas por IDs ausentes, sem depender de dados de cliente. Executa no sandbox/UID/credencial restrita existentes.
- Publicador desta correção preserva estado gravável, privilégios, firewall, túnel e limites da fila. Extrai somente revisão limpa confirmada no Git remoto; exige fila e requisições ociosas, testa leitura de job real através de runtime/gateway e acesso anônimo negado; rollback usa o mesmo estado.

## Validação e publicação

123 testes de conhecimento, medições, ciclo de vida e ativação passaram. O esquema de produção foi validado pelos dois adaptadores corrigidos em transações somente leitura, usando a credencial de diagnóstico existente. O teste da credencial restrita real será obrigatório no ExecStartPre da publicação.

Estado atualizado: **correção publicada na revisão `1831c2f162bf2cfb0a4faeb10104b827f4d61033`**. A publicação foi executada com sudo no terminal Linux, atualizando unidades e release root-owned. Não houve migração, alteração de OS, nova cobrança ou reinicialização do Cous/firmware nesta correção. A análise completa da OS 1159 foi confirmada depois da publicação pelos logs da aplicação, conforme evidência final abaixo.

## Primeira tentativa de publicação

A tentativa da revisão `b00421c2b8b4175ddc17a2ea445e8b57d8c91bde` reverteu automaticamente para `7b5516d56169020cb6b5d9003a23221cfda4dedf`, preservando o estado. A inicialização dos adaptadores no sandbox/credencial restrita e a leitura do job pelo runtime passaram. O publicador usou indevidamente o token de conhecimento na verificação do gateway. O gateway exige `SYSTEMOS_COGNITIVE_TOKEN`, trocando-o internamente pelo token apropriado ao acessar o runtime. Essa checagem foi corrigida e ganhou teste com tokens distintos. As regras de autenticação da aplicação não foram alteradas. Nova publicação ainda pendente de execução privilegiada.

## Publicação confirmada

Em 15/11/2026 às 11h50 (America/Sao_Paulo), o publicador retornou PUBLISHED para `1831c2f162bf2cfb0a4faeb10104b827f4d61033`. O marcador root-owned confirma essa revisão e os serviços runtime/gateway/egress estão ativos. O ExecStartPre validou os dois adaptadores com a credencial/UID restritos; o runtime e gateway responderam 200 para leitura de job existente. Privilégios, firewall e diretório de estado preservados; nenhuma migração, operação financeira ou reinicialização de Cous/firmware executada.

A tentativa real da OS 1159 gravou os IDs de indexação/documento/captura/diagnóstico e resultado cognitivo às 11h51:23. O SystemOS iniciou em seguida a geração narrativa (14 evidências). Durante essa inferência, consultas adicionais ao runtime tiveram timeout; o gateway/forward continuam respondendo à saúde. A implementação da chamada Ollama é síncrona e a conclusão narrativa ainda está em acompanhamento. Não confundir a correção confirmada da inicialização/diagnóstico com comprovação da conclusão do texto.

## Verificação final da OS 1159

Às **11h54:06 de 15/11/2026 (America/Sao_Paulo)**, o SystemOS registrou `Analise OpenTracy concluida` para a ordem interna `4b1c136e-3e75-45b3-92b4-5820df336a32` (OS 1159), trace `bef95443-07e0-42c6-a307-575b705d2d92`, duração 163121,848 ms (cerca de 2min43s). Ollama registrou HTTP 200 para /api/chat no mesmo instante.

Após a conclusão, a consulta de job feita de dentro do container real da API SystemOS usando AI_OPENTRACY_URL e AI_OPENTRACY_COGNITIVE_TOKEN retornou **HTTP 200 em 524 ms**. A mesma consulta sem credencial retornou **401 em 356 ms**. Isso confirma o trajeto API → forward privado → gateway → runtime → PostgreSQL depois da inferência. Nenhuma conclusão sugerida foi aplicada por esta intervenção.

Limitação observada: durante a chamada síncrona de inferência, o event loop do runtime não respondeu a leituras paralelas/saúde dentro do timeout de 5–15 segundos usado no diagnóstico. A análise terminou dentro de seu timeout operacional de 900 segundos. A separação dessa execução bloqueante permanece uma melhoria de disponibilidade; não foi alterada nesta correção de privilégios/esquema e não deve ser considerada resolvida apenas por este sucesso.
