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

122 testes de conhecimento, medições, ciclo de vida e ativação passaram. O esquema de produção foi validado pelos dois adaptadores corrigidos em transações somente leitura, usando a credencial de diagnóstico existente. O teste da credencial restrita real será obrigatório no ExecStartPre da publicação.

Estado deste registro: **correção preparada; ainda não publicada**. É necessário sudo no terminal Linux para atualizar as unidades e a release root-owned. Não houve migração, alteração de OS, nova cobrança ou reinicialização do Cous/firmware nesta correção. A análise completa da OS 1159 precisa ser confirmada depois da publicação; leitura de job/configuração isoladamente não prova a inferência completa.
