# Melhorias inspiradas nos projetos de referência

> **PENDENTE: MCP Tools** (descoberta e execução de Tools MCP por stdio; detalhes em [2026-10-09](2026-10-09-feature-opportunities.md)). Não implementado; adiado pelo usuário em 2026-10-07 e mantido fora da feature 0055. Retomar quando houver um servidor MCP concreto a usar.
>
> **PENDENTE: extensibilidade por entry points** (plugins carregados de pacotes instalados; candidato 5 em [2026-09-23](2026-09-23-opencode-feature-comparison.md)). Não implementado; fora da feature 0055 por falta de um plugin concreto. Retomar quando houver um plugin real a carregar.

Pesquisa em **2026-10-14**. Evidência original e propostas históricas. Fontes primárias consultadas pelo navegador e código local inspecionado. Sem chamadas pagas, instalação de referências ou benchmark de modelos. Links em branches descrevem o conteúdo consultado nesta data e podem mudar.

**Implementado em 2026-10-14, feature 0053 ticket 03:** prefixo de aplicação/projeto antes de Memory, Skills ativos, Summary e Todo; catálogo determinístico; três snapshots completos de produção por modo, com regeneração e isolamento offline. Ver [spec R11–R14/R29–R31](../../specs/0053-stable-sessions-and-recovery.md) e [testes/guia](../../../tests/README.md). A reprodução abaixo permanece histórica; não mede hits, economia ou reutilização do histórico inteiro. Fork foi entregue na feature 0055 (ticket 03, 2026-10-17) como `/fork`: nova Sessão filha autocontida a partir do último turno fechado, pai intacto e retomável, mesmo Workspace Root.

**Implementado e aprovado em 2026-10-15, feature 0053 ticket 05:** `/recover` local para a última execução com mudanças de arquivos, inclusive falhas/Resume, snapshots exatos privados, confirmação `yes`, recusa de conflitos e Retry limpo após restauração. Shell, histórico de backups e redo estão excluídos. Ver [contrato R21–R28](../../specs/0053-stable-sessions-and-recovery.md) e [README](../../../README.md).

**Recomendação:** checkpoints têm o maior benefício funcional; snapshots de prompt/schemas são a melhoria menor e mais rápida. Estabilidade do prefixo merece uma feature própria após definir o contrato de cache. Fork de conversa fica condicionado ao uso real. Esforços abaixo são estimativas de engenharia, não medições.

## Situação atual

Streaming dos quatro Providers e `/report` já estão concluídos na feature 0052 (`.ai/PROJECT_STATE.md:1–15`, `terminal/repl.py:52–57`). Resume, recuperação de exchange interrompido, compression preventiva, busca em logs, skills, instruções de projeto e modos de execução também já existem. Busca de histórico não é uma nova oportunidade: `session_logs.py:183–204,676–678` oferece `search` com consulta.

Os caminhos locais abreviados abaixo têm base em `src/personal_agent/`, exceto quando indicado. A pesquisa anterior de 2026-10-09 continua útil para checkpoints, MCP Tools e jobs, mas suas observações sobre ausência de streaming e relatório ficaram superadas.

## 1. Checkpoint das alterações feitas por tools de arquivos

**Referência:** OpenCode restaura conversa e arquivos com undo/redo e armazena snapshots separadamente do Git do usuário. A documentação também explica que restaurar caminhos afetados pode sobrescrever edições atuais. Fontes: [Snapshots V2](https://dev.opencode.ai/v2/docs/snapshots/) e [implementação de revert consultada](https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/opencode/src/session/revert.ts), especialmente captura/restauração nas linhas 63–66 e 88.

**Lacuna local:** `/undo` apenas remove o último turno e registra `turn_undone` (`terminal/repl.py:1309–1317`). `write`/`edit` gravam bytes diretamente (`tools/workspace.py:347–355`). `apply_patch` conserva originais em memória e os restaura quando a própria aplicação falha (`tools/apply_patch.py:405–442`); isto já fornece rollback de falha, mas não um checkpoint persistente de uma edição bem-sucedida.

**Primeira entrega:** guardar antes/depois somente dos arquivos tocados por `write`, `edit` e `apply_patch`; oferecer comando separado para listar diff e restaurar o último conjunto. Comparar o estado atual com o estado posterior registrado e recusar conflito com edição posterior. Capturar também a ausência do arquivo, para desfazer criação/exclusão. Limitar tamanho/retenção e manter Workspace Root e exclusões de arquivos sensíveis.

**Valor esperado:** recuperar uma edição errada sem confundir undo de conversa com recuperação de arquivos. Esforço médio; a persistência e a proteção contra conflito são parte necessária da feature. Não incluir efeitos de shell na primeira entrega.

**Prova exigida:** criação, edição e exclusão restauráveis após reiniciar; arquivos não tocados preservados; edição externa posterior recusada; falha de snapshot impede anunciar que há recuperação disponível. O limite de escopo precisa aparecer no comando.

## 2. Prefixo de contexto estável, sem mudar a semântica dos comandos

**Referência:** Hermes separa estado de prompt conservado e adições efêmeras; o código restaura os mesmos bytes e a ordem de ferramentas entre turnos. Fontes: [Prompt Assembly](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/prompt-assembly.md) e [conversation_loop.py](https://github.com/NousResearch/hermes-agent/blob/main/agent/conversation_loop.py), função `_restore_or_build_system_prompt`.

**Lacuna local:** a memória aparece antes da identidade e das regras fixas (`routing/router.py:53–56`); summary e todo aparecem antes das instruções de projeto (`routing/router.py:97–115`). O bloco de todo muda ou desaparece ao concluir itens (`tools/todo.py:43–49`), e o prompt é remontado no exchange (`routing/router.py:655`).

**Reprodução offline:** chamar `_build_system_prompt` com memória `Python`, instrução `PROJECT_POLICY` e um todo `run tests`, trocando somente `pending` por `completed`, produziu dois prompts diferentes. Prefixo comum: **121 caracteres**; a instrução de projeto mudou da posição **395** para **361**. Isto prova alteração precoce dos bytes; não prova cache miss real nem economia financeira.

**Primeira entrega:** ordenar identidade/regras fixas e instruções estáveis antes de memória, summary, todo e skills variáveis. Registrar ou testar comprimento do prefixo comum entre inputs preparados. Não congelar a memória inteira durante a sessão: `/remember` promete efeito nos próximos requests (`terminal/repl.py:46`), e instruções de projeto têm recarga deliberada entre tarefas (`tests/test_project_instructions_integration.py:87–108`). Preservar essas obrigações.

**Valor esperado:** aumentar o trecho reutilizável nos Providers que cacheiam prefixos. Esforço pequeno/médio; a economia precisa ser avaliada depois com os campos de cache já agregados por `/report` (`session_report.py:98–109`). Esta pesquisa não especifica habilitação de cache nativo: Anthropic hoje prepara `system` como string (`providers/anthropic.py:74–78`), e parâmetros de cache exigem pesquisa própria antes de implementação.

**Prova exigida:** mutar todo não muda o prefixo fixo; `/remember`, `/forget`, troca de modo e recarga de instruções continuam sendo efetivos; medição conta o input preparado de cada Provider. Não prometer cache hit com base apenas na ordem de strings.

## 3. Snapshot revisável de prompt e schemas, como melhoria de engenharia

**Referência:** Hermes renderiza superfícies reais, conserva fixtures versionadas e verifica se ficaram desatualizadas; revisores veem mudanças em texto e ferramentas. Fonte: [Prompt Assembly — Reviewing changes to the prompt surface](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/prompt-assembly.md#reviewing-changes-to-the-prompt-surface).

**Lacuna local:** há testes úteis de schemas e de comportamento, por exemplo `tests/test_workspace_tools.py:166–174` e `tests/test_project_instructions_integration.py:87–108`. Não encontrei artefato versionado com a superfície completa de prompt mais schemas; não se trata de ausência geral de testes.

**Primeira entrega:** uma fixture determinística por modo (`plan`, `build`, `auto`) renderizada pelo código de produção com Providers falsos, workspace temporário e relógio/configuração fixos. Revisar diff do prompt e do catálogo quando forem alterados. Evitar nove famílias de modelos e pipeline de comentários em PR nesta fase.

**Valor esperado:** detectar alteração acidental de permissões anunciadas, precedência, descrição de tools e tamanho do contexto antes de chamar modelos. Esforço pequeno; é uma melhoria do desenvolvimento, sem novo comando para o usuário.

**Prova exigida:** mudança real de texto/schema falha enquanto a fixture não for atualizada; mudança de relógio, diretório da máquina ou credenciais não muda a fixture. O snapshot complementa testes comportamentais e não demonstra que o modelo seguirá instruções.

## 4. Fork da conversa atual, somente se houver demanda

**Status (2026-10-17, entregue):** implementado na feature 0055 (ticket 03); ver [spec R4–R11](../../specs/0055-fork-jobs-claude-cache.md) e [ADR-0013](../../adrs/0013-fork-copies-into-a-new-session.md). A proposta abaixo é histórica.

**Referência:** DeepSeek Harness documenta fork numa fronteira de turno, com sessão filha e origem registradas. Fontes: [Architecture — fork at a turn boundary](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md#where-new-behavior-goes) e [Sessions — inheritedEventCount](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/session.md#session-public-api). O [README oficial](https://github.com/deepseek-ai/deepseek-harness/blob/master/README.md#developer-preview) continua classificando o projeto como developer preview.

**Lacuna local:** o catálogo de comandos não oferece fork (`terminal/repl.py:28–32`). Nova sessão começa vazia, e Resume continua o mesmo identificador (`call_log.py:157–214`); não há operação pública equivalente de ramificação.

**Primeira entrega:** `/fork` apenas no último turno fechado da conversa atual, criando novo ID, registrando origem e copiando conversa/summary/todo. Definir no brief se tier e progresso serão herdados; o gasto novo não pode somar chamadas herdadas como se fossem chamadas novas. Recusar enquanto houver continuation pendente. Não criar worktree, restaurar arquivos ou executar tools ao copiar.

**Valor esperado:** comparar uma alternativa de solução/modelo mantendo a conversa original. Esforço médio, prioridade inferior; cópia de estado de conversa é mais simples que adicionar sessões simultâneas, mas exige contrato de replay e relatório.

**Prova exigida:** mutar a filha não altera pai; Resume de ambos funciona; herança não duplica custo, execução de tools ou progressão de tarefas. A documentação deve dizer que ambas as conversas continuam no mesmo workspace.

## Decisões que a comparação não justifica

Não há evidência nesta pesquisa de que plataforma de plugins, agentes paralelos, frontend adicional ou cron sejam necessários para este router. MCP Tools permanece opção condicional registrada em `2026-10-09-feature-opportunities.md`, sem integração concreta que a torne prioridade aqui. Jobs em background foram entregues na feature 0055 (ticket 02, 2026-10-17); plugins por entry points continuam pendentes, fora da 0055 por falta de um plugin concreto. O mecanismo comunitário de verification encontrado em Discussions do DeepSeek não foi tratado como capacidade nativa mantida pelo projeto.

Nenhuma alegação de reputação, crescimento de estrelas ou incidente histórico de `CLAUDE.md` foi usada para priorizar. As recomendações vêm de capacidades documentadas e lacunas no código local.
