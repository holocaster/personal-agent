# Comparação funcional com os projetos de referência

Análise em 2026-10-28, sobre `personal-agent` 0.1.0, commit `c4a4ec0`.
Referências identificadas nas pesquisas do próprio repositório: OpenCode,
Hermes Agent e DeepSeek Harness. Não é um benchmark de qualidade dos modelos.

O núcleo de um agente de terminal já está implementado. As diferenças mais
relevantes hoje estão nas integrações executáveis, na memória entre tarefas e
na composição de agentes. Streaming, fork, checkpoints e subagentes deixaram
de ser lacunas, embora seus limites sejam menores que os de algumas referências.

## Método e versões

Leitura de código, catálogo de ferramentas, documentação local e testes focados.
Context7 foi consultado para os três projetos, após resolver seus IDs oficiais:
`/anomalyco/opencode`, `/nousresearch/hermes-agent` e
`/deepseek-ai/deepseek-harness`. Documentação primária também foi aberta na web.
Os documentos externos consultados são de branches móveis; esta comparação não
atribui todas as capacidades a uma release específica. OpenCode possui V1 e V2;
não se deve misturar seus formatos de configuração. Nenhuma configuração externa
é proposta aqui. DeepSeek Harness se declara developer preview.

O lock local fixa MCP 2.2.0, LiteLLM 1.102.0, prompt-toolkit 3.0.53 e pytest 9.1.1.
Esses pacotes contextualizam a implementação; não se atribuiu uma falha às suas APIs.

## Capacidades presentes

| Área | Evidência e limite local |
| --- | --- |
| Execução agentic | Loop de ferramentas, limites de rodadas, validação de correlação e retry no mesmo modelo em `routing/router.py:391` e `:630`. |
| Providers | Cinco implementações registradas em `providers/registry.py:3`: OpenRouter, Anthropic, OpenAI, Gemini e ChatGPT. |
| Arquivos e comandos | Leitura, busca textual, escrita, edição, patch, shell e jobs no catálogo `tools/registry.py:51`. |
| Continuidade | Resume e histórico via Call Log; `/fork` copia o último turno fechado para uma nova sessão (`terminal/repl.py:494`). |
| Recuperação | `/recover` para a última execução que mudou arquivos pelas ferramentas suportadas; recusa conflitos (`file_recovery.py:535`). Não restaura efeitos de shell. |
| Contexto | Compression manual/preventiva e recuperação de overflow; prefixo estável construído em `routing/router.py:34`. |
| Observabilidade | `/report` agrega execução, uso e proveniência de custo (`session_report.py:224`). Não demonstra economia por si só. |
| Personalização | Instruções de projeto, descoberta e leitura de skills (`workspace_skills.py:99`, `:146`) e papéis de subagentes. |
| Delegação | Processo separado, sessão filha, restrição de ferramentas e confirmações encaminhadas ao pai (`subagents/worker.py:51`). |

Os caminhos da tabela são relativos a `src/personal_agent/`. A presença dessas
capacidades não prova equivalência de UX, robustez ou taxa de conclusão com os
outros produtos. Pesquisas antigas que apontam sua ausência foram superadas.

## Diferenças que afetam o uso

### 1. MCP Resources não substitui MCP Tools

O catálogo expõe somente `mcp_list_resources`, `mcp_list_resource_templates` e
`mcp_read_resource` (`tools/registry.py:327`). A configuração aceita um servidor
local por comando/args (`tools/mcp_resources.py:38`); não há descoberta e execução
de ferramentas MCP nesse caminho.

OpenCode documenta ferramentas MCP locais e remotas disponíveis ao modelo.
Isso permite integrações executáveis que o suporte local a recursos não cobre.
Fonte: [OpenCode MCP](https://opencode.ai/docs/mcp-servers/).

**Impacto:** um servidor que exponha uma busca ou operação somente como Tool
não pode ser consumido como tal pelo personal-agent. Esta é a expansão mais
direta se houver um servidor concreto necessário. A pesquisa local registra
que ela foi adiada; diferença funcional não significa obrigação de implementá-la.

### 2. Memória explícita versus aprendizado assistido pelo agente

Localmente, `/remember` e `/forget` administram notas; o arquivo padrão é global,
`~/.personal_agent/memory.jsonl` (`memory.py:5`), e todas as notas carregadas entram
no prompt (`routing/router.py:97`). Há busca de histórico, mas isso não equivale
a seleção de memórias por relevância ou manutenção autônoma de skills.

Hermes documenta memória curada pelo agente, criação e melhoria de skills e
busca FTS5 de sessões. Fonte: [Hermes README](https://github.com/NousResearch/hermes-agent/blob/main/README.md)
e [Skills vs Memory](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/work-with-skills.md).

**Impacto:** no personal-agent a continuidade depende mais de notas explícitas,
instruções do projeto e consultas ao histórico. Se isso causar repetição real,
avaliar primeiro escopo por projeto e recuperação seletiva; não pressupor que
gravação automática ou um banco vetorial sejam necessários. O ai-memory do
ambiente de desenvolvimento não prova que o produto implemente essas capacidades.

### 3. Subagentes existem, com composição restrita

O lock impede concorrência (`subagents/__init__.py:67`), o filho recebe a
configuração do pai (`:30`, `:93`) e executa uma tarefa isolada. O worker limita
ferramentas e não recebe o histórico completo do pai (`subagents/worker.py:64`,
`:78`). Processo separado preserva estado de execução; os arquivos continuam
no mesmo workspace, sem sandbox de filesystem.

DeepSeek Harness documenta filhos continuáveis, mensagens e workflows com
pipeline/paralelismo e seleção de rota por agente. Fonte:
[catálogo de ferramentas](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/tool-catalog.md).

**Impacto:** o personal-agent atende delegação sequencial com papéis, mas não
equivale a uma equipe persistente coordenada por mensagens. Paralelizar escrita
no mesmo workspace acrescentaria conflitos; só vale expandir quando tarefas
reais demonstrarem um gargalo. O `/fork` de conversa não é um worktree Git.

### 4. Ferramentas de desenvolvimento e extensões

O catálogo local oferece busca textual e shell; não foi encontrada integração
LSP, API pública de servidor ou descoberta de plugins por entry points no código
inspecionado. OpenCode documenta diagnósticos LSP e interfaces terminal, desktop
e IDE. DeepSeek Harness organiza o produto como plugins e oferece Web UI.
Fontes: [OpenCode LSP](https://opencode.ai/docs/lsp/),
[interfaces](https://opencode.ai/docs/) e
[Harness README](https://github.com/deepseek-ai/deepseek-harness/blob/master/README.md).

**Impacto:** feedback de compilador/type checker precisa passar por comandos,
e novas integrações nativas exigem alterar o programa. Isso não impede validar
código: a própria documentação LSP recomenda verificações de projeto. Uma
plataforma de plugins e outra interface só se justificam por uma necessidade
concreta que MCP ou shell não atendam.

### 5. Jobs locais não equivalem a automações persistentes

`tools/jobs.py:73` inicia processos acompanhados pelo runtime. Hermes documenta
cron, entrega em canais de mensagens e backends de terminal locais/remotos,
incluindo Docker. Fonte: [Hermes README](https://github.com/NousResearch/hermes-agent/blob/main/README.md).

**Impacto:** o personal-agent tem execução em background durante seu uso, mas
não oferece o mesmo produto de assistente sempre disponível. Para o objetivo
de agente de terminal, essa diferença pode ser uma escolha saudável de escopo.

## Limites operacionais relevantes

- Shell executa sob a conta do usuário, sem confinamento; herda o ambiente com
  exclusão específica de `TAVILY_API_KEY` (`tools/shell.py:201`). Confirmação e
  detecção de comandos perigosos não constituem sandbox. Isso está documentado.
- Recuperação de arquivos não é backup completo e não cobre efeitos de shell.
- Contabilidade e afinidade de cache não provam redução de custo ou latência.
  Não há benchmark comparativo nesta análise.
- Seleção explícita do modelo é decisão do produto; ausência de troca automática
  não é regressão a corrigir. O catálogo também não garante acesso remoto.

## Prioridade sugerida

1. Medir tarefas reais comparáveis: mesma tarefa, modelo, workspace inicial e
   critério de aceite; registrar conclusão, intervenção humana, tempo e custo.
   Separar cache frio e quente. Isso determina qual diferença importa no uso.
2. Se uma integração estiver bloqueando trabalho, entregar MCP Tools para um
   servidor concreto, reaproveitando validação, confirmação e logs existentes.
3. Se o problema for repetição de contexto, avaliar memória por projeto e busca
   seletiva antes de criar aprendizado automático.
4. Se houver demanda por execução sem supervisão, tratar isolamento e limites
   operacionais antes de ampliar autonomia.

LSP, UI web, plugins e paralelismo ficam condicionados a casos de uso. Não há
evidência aqui para copiar a arquitetura inteira das referências ou alegar que
o projeto produz código pior apenas por ter menos funcionalidades.

## Verificação e ressalva encontrada

A bateria inicial reuniu 296 casos de MCP Resources, memória, subagentes, fork,
recuperação e snapshots de prompt. Foi interrompida durante a execução;
não há resultado completo e ela não deve ser apresentada como aprovada.

Uma execução separada e concluída de `tests/test_memory.py`,
`tests/test_prompt_surface.py`, `tests/test_fork.py` e
`tests/test_file_recovery.py` resultou em **189 passed em 44,44 s**.

Foi reproduzida isoladamente uma falha:
`tests/test_mcp_resources.py::test_ctrl_c_reaps_server`. Após SIGINT, o processo
não encerrou dentro dos sete segundos esperados por `process.wait(timeout=7)`
na linha 239. O teste isolado terminou com **1 failed em 8,02 s**.
Comando: `.venv/bin/pytest -q tests/test_mcp_resources.py::test_ctrl_c_reaps_server --tb=short`.

Isso comprova uma falha de cancelamento no cenário de teste deste ambiente,
mas não estabelece ainda sua causa nem a extensão em uso real. Não se atribui
o resultado ao SDK, ao sandbox ou ao código de aplicação sem investigação
adicional. Convém esclarecer esse comportamento antes de ampliar MCP.

Não foram executados benchmarks entre produtos, chamadas pagas ou login em
serviços. Código de aplicação e testes permaneceram inalterados.

## Aprofundamento: cancelamento MCP

O teste `test_ctrl_c_reaps_server` inicia um cliente em processo separado e um
servidor artificial configurado para não responder a `resources/list`. Depois
de observar atividade do protocolo, envia SIGINT ao cliente, espera sua saída
em até sete segundos e verifica o marcador de encerramento do servidor.
O sinal é enviado ao processo cliente, não diretamente ao servidor.
Fontes: [teste](../../tests/test_mcp_resources.py#L220) e
[servidor de teste](../../tests/fixtures/mcp_server.py).

A observação comprovada é que o cliente não terminou nesse prazo. Como o teste
falha antes das verificações seguintes e força a saída do cliente na limpeza,
o resultado não prova travamento permanente, servidor órfão ou perda de dados.
Também não exercita toda a interface interativa. O impacto possível no produto
é Ctrl+C demorar a devolver o controle, com limpeza de processos ainda pendente.

O fluxo esperado é interromper a espera, fechar a comunicação, aguardar o
servidor e terminar seu processo se necessário. Para stdio, a especificação
prescreve fechar a entrada do servidor, aguardar e escalar para SIGTERM e
SIGKILL se ele não encerrar. Fonte:
[MCP — Shutdown](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle#shutdown).

A implementação local chama `asyncio.run(_execute(...))`, envolve a operação
em `anyio.move_on_after(30)` e delega o transporte ao SDK MCP. O código instalado
do SDK 2.2.0, em `mcp/client/stdio.py`, já inclui encerramento protegido contra
cancelamento e esperas limitadas. Context7 foi consultado para o SDK e a leitura
local foi usada para conferir a versão instalada. Portanto, ainda não é correto
concluir que faltou simplesmente matar o processo ou que o prazo de 30 segundos
explica a falha. Fonte local:
[execução MCP](../../src/personal_agent/tools/mcp_resources.py#L164).

Próxima investigação proposta: capturar a pilha das tarefas e o estado dos
processos durante a espera, identificar a etapa bloqueada e então verificar
o comportamento pelo caminho interativo. Aumentar o timeout do teste sem essa
evidência esconderia o sintoma. Nenhuma correção ou atualização de dependência
foi implementada nesta análise.

## Aprofundamento: acesso do shell e dos subagentes

O shell executa programas com as permissões da conta que iniciou o agente.
Definir `cwd` como Workspace Root estabelece apenas o diretório inicial;
não impede acessar outros caminhos. Um comando autorizado pode ler ou alterar
outros arquivos acessíveis à conta e usar a rede conforme as restrições do
ambiente. Fonte: [criação do processo](../../src/personal_agent/tools/shell.py#L218).

Isso inclui comandos comuns de desenvolvimento: executar testes também
executa código do repositório. Aprovar `pytest`, por exemplo, não restringe o
código dos testes a ler arquivos de teste. Instalação de dependências e scripts
de build também precisam ser considerados ao definir o acesso necessário.

O ambiente do shell herda as variáveis do processo, removendo especificamente
`TAVILY_API_KEY`. Outras credenciais exportadas podem ficar disponíveis aos
comandos. Isso comprova possibilidade de acesso, não um vazamento observado.
Fonte: [shell_environment](../../src/personal_agent/tools/shell.py#L201).

Há proteções existentes: confirmação em build, bloqueio de shell em plan,
reconhecimento de padrões perigosos, timeout e encerramento de grupos de
processos. Elas reduzem acidentes, mas não impõem limites de filesystem ou
rede. O próprio código prevê processos que escapem do grupo e possam continuar
vivos. `/recover` cobre alterações feitas pelas ferramentas de arquivos
suportadas; não desfaz efeitos de shell nem substitui backup.
Fontes: [confirmação e checkpoint](../../src/personal_agent/tools/registry.py#L725)
e [limpeza do shell](../../src/personal_agent/tools/shell.py#L263).

Os subagentes têm processo e contexto separados, mas compartilham o workspace.
Essa separação protege o estado interno da execução e da conversa; não cria
uma cópia isolada dos arquivos. O worker restringe as ferramentas às capacidades
do pai e do papel, encaminha confirmações ao pai e a delegação aceita apenas
um filho ativo por vez. Há ainda tentativa de interrupção seguida de término
forçado do worker quando necessário.
Fontes: [capacidades do filho](../../src/personal_agent/subagents/worker.py#L51),
[exclusão de concorrência](../../src/personal_agent/subagents/__init__.py#L67)
e [encerramento](../../src/personal_agent/subagents/__init__.py#L180).

Uma consequência importante: um papel com shell pode modificar arquivos por
comandos mesmo sem receber `write`, `edit` ou `apply_patch`. Retirar essas
ferramentas não torna um revisor somente leitura se o shell continuar permitido.
Isso deve orientar a revisão dos papéis antes de ampliar autonomia.

## Proposta discutida: sandbox com acesso suficiente à tarefa

Sandbox significa acesso delimitado, não ausência de acesso. Uma configuração
possível para um implementador seria:

| Recurso | Acesso proposto |
| --- | --- |
| Arquivos do projeto | Leitura e escrita |
| Python, Java, Git e ferramentas de build | Leitura e execução |
| Diretórios temporários | Leitura e escrita |
| Dependências instaladas | Leitura e execução |
| Caches de build necessários | Escrita nos caminhos específicos necessários |
| Outros projetos, documentos pessoais e `.ssh` | Bloqueados por padrão |
| Rede | Conforme a necessidade da tarefa |
| Credenciais | Somente as necessárias à operação |

Nesse desenho, leitura, edição, patch e shell continuam disponíveis dentro
dos limites concedidos. O agente pode modificar código, compilar e executar
testes; tentativas de acesso fora dos limites são bloqueadas pelo mecanismo de
isolamento. Quando necessário, caminhos adicionais, download de dependências
ou acesso a um banco de desenvolvimento podem ser concedidos especificamente.
Uma configuração que impeça necessidades normais da tarefa precisa ser revista.

A diferença para a situação atual é que o limite também alcançaria os programas
executados pelo shell e seus descendentes, em vez de depender apenas das
validações das ferramentas de arquivos. Para subagentes, o acesso poderia ser
adequado ao papel: leitura para análise e escrita no projeto para implementação.

Também foi discutida a separação entre chamadas ao Provider e comandos: o
processo responsável pelo modelo manteria a credencial, enquanto o ambiente do
shell não a receberia. Assim, testes do projeto não precisariam acessar a chave
usada para conversar com o modelo. Essa separação exigiria um limite efetivo
entre processos e acesso a arquivos, não apenas remover uma variável.

A proposta inicial é concentrar o isolamento no shell e seus processos filhos,
preservando escrita no projeto, temporários e ferramentas instaladas. Não se
propôs criar uma sandbox diferente para cada ferramenta. Esse primeiro recorte
não equivale a isolar todo o produto: servidores MCP locais e outros caminhos
de execução precisam ser considerados separadamente para uma garantia global.

Trata-se de uma proposta de desenho, sem mecanismo escolhido ou validação no
ambiente do usuário. Não houve autorização de implementação nesta conversa.
Antes de adotá-la, seria necessário verificar builds, testes, dependências,
rede, cancelamento e bloqueio de acesso fora dos limites. Nenhuma prova
destrutiva foi executada.
