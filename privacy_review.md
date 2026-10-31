# Revisão de dados pessoais — 2026-10-31

Há dados sensíveis na cópia local. Todos os caminhos identificados estão cobertos pelas regras atuais de ignore. Esta revisão não comprova que essas informações tenham sido publicadas.

## Achados

### P01 — Alta sensibilidade: duas credenciais no `.env`

- `.env:2`: `OPENROUTER_API_KEY` preenchida com formato de chave.
- `.env:7`: `OPENAI_API_KEY` preenchida com formato de chave.
- A validade das chaves não foi testada. Seus valores foram omitidos.
- Não foram encontradas cópias dessas duas chaves nos demais arquivos examinados, inclusive no ambiente virtual e no pacote em `dist/`.
- `.gitignore:7` exclui o `.env` da inclusão normal em um novo repositório. Compartilhar a pasta inteira ainda pode expor as credenciais e permitir uso das contas se forem válidas.

### P02 — Identificação local no ambiente virtual

- `.venv/pyvenv.cfg:1`, `.venv/bin/activate:81` e `.venv/bin/personal-agent:1` contêm caminhos com o nome do usuário do sistema.
- Também existem referências nos demais scripts, metadados de instalação, arquivos compilados e um link simbólico do ambiente.
- São arquivos gerados localmente. `.gitignore:4` exclui `.venv/`; o ambiente deve ser recriado na máquina de destino.

### P03 — Caminhos locais em arquivos compilados

- 233 arquivos em diretórios `__pycache__` do projeto contêm o nome do usuário em caminhos locais.
- O código-fonte atual não apresentou esse identificador; as referências permanecem nos arquivos compilados gerados pelo Python.
- `.gitignore:1` e `.gitignore:2` excluem esses arquivos. Eles não precisam acompanhar o código compartilhado.

## Verificação

- Examinados 825 arquivos do projeto, incluindo ocultos e caches, e as 38 entradas do pacote wheel em `dist/`.
- No ambiente virtual, examinadas 12.578 entradas de arquivos e links para localizar o identificador do usuário e cópias das duas credenciais conhecidas.
- Procurados caminhos pessoais, e-mails, formatos de credenciais, chaves privadas, JWTs, URLs com senha, endereços IP e padrões comuns de documentos e contatos pessoais nos arquivos do projeto.
- Os e-mails e caminhos textuais encontrados são exemplos de teste; os endereços IP encontrados são de loopback. Os demais candidatos a credenciais foram revisados e eram exemplos ou trechos de nomes de arquivos.
- Não foram encontrados dados pessoais pelos padrões verificados no código-fonte, documentação, configurações compartilháveis, testes em texto ou conteúdo do wheel. O `.env.example` contém exemplos.
- As regras de ignore foram verificadas em um repositório temporário: todos os 2.969 caminhos com credenciais conhecidas ou identificador pessoal seriam ignorados. O projeto não foi reinicializado como repositório.

## Limites

Nenhum arquivo existente foi alterado ou apagado. Não foram consultados serviços externos, o antigo repositório remoto ou a validade das credenciais. A revisão combina padrões e inspeção dos candidatos; não garante ausência de informação pessoal em formatos não reconhecidos. As regras de ignore não impedem inclusão forçada ou compartilhamento direto da pasta.
