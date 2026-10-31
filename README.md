# Simulado OAB — Backend

API REST para cadastro e autenticação de estudantes e persistência dos resultados dos simulados do projeto [Simulado OAB](https://github.com/DanilloTeod/simu-oab). A aplicação foi construída com Flask, Flask-SQLAlchemy, SQLite e JWT.

## Funcionalidades

- Cadastro de estudantes com senha armazenada como hash.
- Login e emissão de token JWT com validade de uma hora.
- Consulta do perfil do estudante autenticado.
- Salvamento do resultado e das respostas de um simulado.
- Histórico de simulados protegido por JWT.
- Painel administrativo com acesso definido por `ADMIN_EMAILS`.
- Contagem de estudantes online a partir de heartbeats persistidos no SQLite.
- Criação das tabelas SQLite durante a inicialização da aplicação.

As questões do exame **não** são servidas por esta API: o frontend carrega os arquivos JSON de questões localmente.

## Requisitos

- Python 3.10 ou superior.
- `pip`.

## Executar localmente

No diretório do backend:

```bash
cd simu-oab-backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure a chave usada para assinar os tokens. É possível defini-la no ambiente:

```bash
export JWT_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

Ou crie um arquivo `.env` na raiz do backend, que não deve ser versionado:

```dotenv
JWT_SECRET_KEY=uma-chave-aleatoria-forte
```

`DATABASE_URL` pode apontar para um arquivo SQLite absoluto. Sem essa variável, o app usa `instance/banco_dados.db` relativo à aplicação. `FRONTEND_ORIGINS` recebe uma lista de origens permitidas separadas por vírgula; o padrão permite Vite local e `https://simu-oab.vercel.app`.

Inicie o servidor:

```bash
python run.py
```

Por padrão, o Flask inicia em `http://127.0.0.1:5000`. A aplicação encerra com erro se `JWT_SECRET_KEY` não estiver configurada. Na inicialização, as tabelas são criadas no SQLite em `instance/banco_dados.db` se ainda não existirem. `db.create_all()` não substitui migrações quando o esquema evolui.

## API

As rotas recebem e retornam JSON. Os exemplos usam a base local `http://127.0.0.1:5000`.

### `POST /api/cadastro`

Cadastra um estudante. Nome, email e senha são obrigatórios; a senha deve ter pelo menos oito caracteres. O email é normalizado para minúsculas.

```json
{
  "nome": "Ana Silva",
  "email": "ana@example.com",
  "senha": "senha-com-oito-caracteres"
}
```

Resposta `201`:

```json
{
  "mensagem": "Estudante cadastrado com sucesso!"
}
```

Retorna `400` para dados inválidos e `409` quando o email já está cadastrado. O cadastro não autentica o estudante; faça login para receber um token.

### `POST /api/login`

Autentica com email e senha:

```json
{
  "email": "ana@example.com",
  "senha": "senha-com-oito-caracteres"
}
```

Resposta `200`:

```json
{
  "mensagem": "Login aprovado",
  "token": "<jwt>",
  "estudante": {
    "id": 1,
    "nome": "Ana Silva"
  },
  "is_admin": false
}
```

Retorna `400` se os dados estiverem ausentes ou inválidos e `401` se as credenciais não forem válidas.

### `GET /api/perfil`

Retorna `id`, `nome` e `email` do estudante autenticado. Envie o token no cabeçalho:

```http
Authorization: Bearer <jwt>
```

Retorna `404` se o estudante associado ao token não existir. As rotas protegidas exigem um token válido e não expirado.

### `POST /api/simulados/salvar`

Rota protegida. Envie o cabeçalho `Authorization: Bearer <jwt>` e os dados usados pelo frontend:

```json
{
  "edition": 45,
  "total_questions": 25,
  "score": 18,
  "answers": [
    {
      "question_id": 1,
      "subject": "Ética",
      "selected_option": "a",
      "is_correct": true
    }
  ]
}
```

O resultado fica associado ao estudante identificado pelo token. Resposta `201`:

```json
{
  "mensagem": "Simulado salvo com sucesso!",
  "resultado_id": 1
}
```

Sem token válido, a extensão JWT rejeita a requisição. O registro contém edição, quantidade total de questões, pontuação, respostas marcadas e data de envio.

### `GET /api/simulados/historico`

Rota protegida. Envie o JWT no cabeçalho `Authorization: Bearer <jwt>`. A resposta contém somente os simulados do estudante autenticado, do mais recente para o mais antigo:

```json
[
  {
    "id": 1,
    "edition": 45,
    "total_questions": 25,
    "score": 18,
    "answers": [
      {
        "question_id": 1,
        "subject": "etica",
        "selected_option": "a",
        "is_correct": true
      }
    ],
    "submitted_at": "2026-10-31T14:08:44+00:00"
  }
]
```

O frontend usa a edição e os identificadores das respostas para carregar os enunciados, alternativas, gabaritos e comentários do arquivo de questões correspondente.

## Integração com o frontend

O cliente da API está em [`src/js/api.js`](../simu-oab-frontend/src/js/api.js). Atualmente, ele chama o backend publicado em `https://danilloteod.pythonanywhere.com` para:

| Ação no frontend | Requisição |
| --- | --- |
| Cadastro | `POST /api/cadastro` |
| Login | `POST /api/login` |
| Salvar resultado | `POST /api/simulados/salvar` |
| Consultar histórico | `GET /api/simulados/historico` |
| Registrar presença | `POST /api/presenca` |
| Painel administrativo | `GET /api/admin/dashboard` |

Após o login, o frontend guarda o JWT em `localStorage` na chave `token_oab` e o nome em `user_name`. Ao salvar um simulado, envia o JWT como `Bearer` e o objeto com `edition`, `total_questions`, `score` e `answers`. O frontend só tenta salvar o resultado quando encontra um token.

No modo de desenvolvimento, o frontend usa `http://127.0.0.1:5000`; no build de produção, usa `https://danilloteod.pythonanywhere.com`. As questões continuam sendo carregadas separadamente pelo frontend a partir de `/data/questoes_oab_<edição>_tipo1.json`. O backend aceita as origens `http://localhost:5173`, `http://127.0.0.1:5173` e `https://simu-oab.vercel.app` por padrão. Defina `FRONTEND_ORIGINS` para sobrescrever a lista, usando origens completas separadas por vírgula.

## Painel administrativo e presença online

Configure `ADMIN_EMAILS` no ambiente do backend com os emails autorizados, separados por vírgula. Exemplo para ambiente local:

```dotenv
ADMIN_EMAILS=admin@example.com
```

O painel administrativo requer login e valida o email autorizado no backend. A rota `GET /api/admin/dashboard` retorna dados pessoais dos estudantes e resultados somente para administradores.

O frontend visível envia um heartbeat a cada 30 segundos, ao abrir a página e ao retornar para ela. `POST /api/presenca` recebe um identificador UUID aleatório do navegador e, quando há login, associa a sessão ao estudante. O painel considera online quem teve atividade nos últimos dois minutos; estudantes autenticados são contados uma vez por aluno, e visitantes anônimos uma vez por sessão de navegador. A presença é persistida no banco do backend e registros inativos por mais de um dia são removidos em heartbeats posteriores. A hospedagem do frontend na Vercel não mantém esse contador: ela apenas envia os heartbeats para a API e consulta os totais.

## Deploy no PythonAnywhere

1. Clone o repositório para um diretório persistente, por exemplo `/home/SEU_USUARIO/simu-oab-backend`.
2. Crie o ambiente virtual compatível com a versão Python selecionada na Web tab e instale as dependências com `pip install -r requirements.txt`.
3. Crie a pasta de dados se necessário e configure as variáveis no arquivo WSGI (não versione os valores secretos):

   ```python
   import os
   os.environ["JWT_SECRET_KEY"] = "gere-uma-chave-secreta-forte"
   os.environ["ADMIN_EMAILS"] = "seu-email-de-admin@example.com"
   os.environ["DATABASE_URL"] = "sqlite:////home/SEU_USUARIO/simu-oab-backend/instance/banco_dados.db"
   os.environ["FRONTEND_ORIGINS"] = "https://simu-oab.vercel.app"

   import sys
   project_home = "/home/SEU_USUARIO/simu-oab-backend"
   if project_home not in sys.path:
       sys.path.insert(0, project_home)
   from run import app as application
   ```

   No URL SQLite, quatro barras após `sqlite:` indicam caminho absoluto Unix. A pasta `instance` e o arquivo devem ficar em armazenamento persistente da conta; não use `/tmp` nem o diretório do ambiente virtual.
4. Na Web tab, escolha o ambiente virtual, salve a configuração WSGI e recarregue a aplicação.
5. Publique o frontend na Vercel. Em produção, o cliente usa `https://danilloteod.pythonanywhere.com`; o CORS precisa incluir a origem exata do domínio Vercel.
6. Abra o site publicado, faça login novamente com uma conta existente cujo email esteja em `ADMIN_EMAILS`. O botão **Admin** aparece na barra superior depois do login.

Se já existe um banco com dados no servidor, mantenha `DATABASE_URL` apontando exatamente para esse arquivo. Se estiver migrando um banco local, faça uma cópia de segurança e transfira o arquivo para o armazenamento persistente antes de apontar a aplicação para ele. `db.create_all()` cria tabelas ausentes, mas não migra nem altera tabelas existentes.

## Testes

As dependências incluem `pytest`; execute a suíte com:

```bash
python -m pytest -q
```

Os testes usam um banco SQLite em memória e cobrem login administrativo, autorização, histórico, presença online e salvamento de simulados.
