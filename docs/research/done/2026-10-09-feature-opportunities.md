# Oportunidades de features

> **PENDENTE: MCP Tools** (descoberta e execução de Tools MCP por stdio, seção abaixo). Não implementado; adiado pelo usuário em 2026-10-07 e mantido fora da feature 0055. Retomar quando houver um servidor MCP concreto a usar.

**Status (2026-10-17): relatório local e streaming dos quatro Providers implementados e revisados na feature 0052; checkpoints de arquivos entregues como `/recover` na feature 0053 (ticket 05). Jobs em background entregues na feature 0055 (ticket 02, 2026-10-17): `shell` com `background: true`, `job_status`, `job_stop` e `/jobs`. MCP Tools (adiado pelo usuário em 2026-10-07) continua proposto.** A pesquisa abaixo retrata o código de 2026-10-09, Context7 e fontes oficiais. Não houve chamadas pagas nem benchmark live. Verificação final: `tickets/0052-session-report-streaming/feature.review.md`.

## Prioridade sugerida

| Ordem | Feature | Retorno esperado | Esforço relativo |
| --- | --- | --- | --- |
| 1 | Relatório local da sessão | Entender custo, latência e falhas sem abrir JSONL | Pequeno |
| 2 | Streaming | Ver conteúdo antes do fim da geração | Médio |
| 3 | Checkpoints de arquivos | Recuperar edições feitas pelo agente | Médio |
| Condicional | MCP Tools | Acessar uma integração concreta já desejada | Médio |
| Depois | Jobs em background | Manter servidores/testes longos em execução | Médio/alto |

Esforço e retorno são avaliações de engenharia, não benchmarks. As lacunas estão comprovadas no código; a ordem depende do uso real.

## Streaming no terminal

**Observação comprovada:** `providers/http.py:21-22` lê o corpo inteiro antes de fazer `json.loads`; `providers/openrouter.py:37-49` não solicita streaming; `providers/chat_completions.py:55-70` recebe uma mensagem já completa. O contrato atual retorna `AssistantMessage` mais usage (`providers/openrouter.py:34`).

**Valor esperado, por inferência:** mostrar o texto conforme chega reduz o tempo até o usuário ver conteúdo. Não prova redução no tempo total de geração nem resolve, sozinho, a demora do avaliador de tier.

**Documentação:** `stream: true` habilita SSE. Comentários começando com `:` não são JSON; eventos podem atravessar blocos de leitura. No Chat Completions atual do OpenRouter, o chunk final de usage contém uma escolha com delta vazio e repete `finish_reason`; não deve gerar outra conclusão. Erros após o envio dos headers chegam em eventos SSE mesmo com HTTP 200, inclusive antes do primeiro token. Cancelar a conexão só garante interrupção de processamento/cobrança nos provedores que suportam isso. Fonte: [OpenRouter — Streaming](https://openrouter.ai/docs/api_reference/streaming).

Tool calls também chegam em deltas. A documentação de wire format do OpenRouter mostra identificação por `index` e exige concatenar fragmentos de `function.arguments` da mesma chamada antes de interpretar o JSON. Fontes: [Client Tools](https://openrouter.ai/docs/guides/features/tool-calling#streaming-with-tool-calls), [wire format oficial](https://github.com/openrouterteam/docs/blob/main/guides/ori/intern-chat.mdx).

**Escopo mínimo proposto:** OpenRouter primeiro; enviar deltas de texto ao terminal, montar a mesma mensagem final e conservar o usage para o log existente. Montar chamadas de tools completas antes de validar/executar. Preservar as demais implementações de Provider sem streaming. Incluir o caminho HTTP, o Provider, o roteamento, a renderização e os testes de Provider/REPL.

**Risco:** resposta parcial não pode parecer concluída após erro ou cancelamento. Retry automático depois de já mostrar texto precisa de regra explícita para evitar saída duplicada; tools não podem ser executadas a partir de argumentos incompletos. Usage ausente não deve virar custo zero.

**Verificação futura:** SSE simulado com UTF-8/eventos partidos entre leituras, comentários, duas tools intercaladas, JSON parcial, usage final e erro HTTP 200. Confirmar que nenhum efeito de tool ocorre antes de a mensagem ser validada e que o log guarda uma resposta final única.

## MCP Tools além de Resources

**Observação comprovada:** `tools/registry.py:316-338` registra somente listar Resources, listar templates e ler Resource. `tools/mcp_resources.py:164-175` exige a capability Resources e executa apenas essas operações. `tools/mcp_resources.py:38-53` aceita um servidor local stdio. Isso não oferece descoberta e execução de Tools MCP.

**Versão:** `pyproject.toml:9` permite `mcp>=2,<3`; `uv.lock:1040-1041` fixa **2.2.0**, também instalada na `.venv`. Context7 oferece v2.0.0 como referência versionada, portanto as assinaturas foram confirmadas no código 2.2.0: `Client.list_tools(cursor=..., cache_mode=...)` e `Client.call_tool(name, arguments=..., read_timeout_seconds=...)`. Fonte: [SDK Python 2.2.0 — Client](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/client/client.py).

**Documentação:** Resources expõem contexto identificado por URI; Tools representam funções com nome e schema. `tools/list` descobre ferramentas com paginação; `tools/call` recebe nome e argumentos. A specification atual exige tratar annotations como não confiáveis salvo servidores confiáveis. Resultados podem conter texto, conteúdo estruturado ou mídia; falhas de execução podem usar `isError`. Fontes: [MCP Resources, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/resources), [MCP Tools, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).

**Valor esperado, por inferência:** reutilizar um servidor MCP que o usuário já utiliza para consultar documentação ou sistemas externos, sem implementar cada integração no agente. O valor depende de haver pelo menos uma integração concreta desejada.

**Escopo mínimo proposto:** manter um servidor stdio e descobrir/executar somente ferramentas selecionadas explicitamente pelo usuário. Reutilizar o registro, a validação e a confirmação existentes (`tools/registry.py:509-537`), preservar timeout/limite de saída e identificar servidor + ferramenta no log. Suportar texto e conteúdo JSON; rejeitar mídia e interações não suportadas com erro claro. Não acrescentar HTTP remoto, OAuth, múltiplos servidores ou um marketplace nessa primeira entrega.

**Risco:** ferramentas externas podem alterar dados ou enviar conteúdo para fora do workspace; annotations como `readOnlyHint` não autorizam executar sem confirmação. Respostas e descrições são dados externos. A restrição local de arquivos do agente não limita o processo MCP. Ao reutilizar conexões abertas somente por operação, verificar se o servidor escolhido depende de estado em memória entre chamadas.

**Verificação futura:** servidor de fixture com Tools capability e sem Resources, paginação, argumentos inválidos, negação de confirmação, `isError`, timeout e resultado excessivo. Provar que chamadas rejeitadas nunca chegam ao servidor e que resultado estruturado não se perde.

## Relatório local da sessão

`call_log.py:562-610` já registra `latency_ms`, custo, cache e propósito da chamada. O leitor `session_logs` já limita a leitura. Proposta: um `/report` local que agrega tempo de chamadas por avaliação de tier/tarefa/compressão, retries/erros e custo/cache, distinguindo valor desconhecido de zero. Sem chamada ao modelo nem dashboard.

Isso pode orientar as próximas decisões de performance. Limite: latência do Provider não identifica causalmente fila, rede ou tempo de geração; tempos de ferramentas e espera humana exigem verificar a instrumentação existente. Verificação futura: fixture de log com mistura de propósitos, retry e usage ausente.

## Checkpoints e restauração de arquivos

`terminal/repl.py:1276-1284` implementa `/undo` removendo a conversa, sem restaurar arquivos. Proposta: persistir snapshots antes/depois de `write`, `edit` e `apply_patch`; oferecer restauração separada com diff e confirmação. Recusar sobrescrever uma alteração posterior feita pelo usuário. Não prometer desfazer comandos shell.

Git 2.43.0 está instalado. `git restore` usa o index por padrão; `--source` usa a árvore indicada. `HEAD` não representa alterações locais não commitadas anteriores à tarefa. Portanto, simplesmente restaurar de `HEAD` pode apagar trabalho do usuário; snapshots diretos evitam alterar Git/index. Fonte: [git-restore 2.43.0](https://git-scm.com/docs/git-restore/2.43.0).

Risco: perda de dados se a restauração não comparar o estado atual com o snapshot posterior. Verificação futura: criação/edição/exclusão e recusa quando houver edição posterior, preservando arquivos não tocados pelo agente.

## Jobs em background, depois

**Status (2026-10-17, entregue):** implementado na feature 0055 (ticket 02); ver [spec R12–R16](../../specs/0055-fork-jobs-claude-cache.md). A análise abaixo é histórica.

`tools/shell.py:169-178` e `tools/shell.py:235-238` encerram o grupo de processos ao retornar. Proposta posterior: ciclo explícito start/status/stop e saída limitada para servidores de desenvolvimento e testes longos. Não basta aumentar o timeout. Risco: processos órfãos e acúmulo de saída; exigir limpeza e encerramento verificáveis. A complexidade de ciclo de vida justifica adiar até existir demanda concreta.
