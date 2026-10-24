# Simulado OAB — Backend

API REST para cadastro e autenticação de estudantes e persistência dos resultados dos simulados do projeto [Simulado OAB](https://github.com/DanilloTeod/simu-oab). A aplicação foi construída com Flask, Flask-SQLAlchemy, SQLite e JWT.

## Funcionalidades

- Cadastro de estudantes com senha armazenada como hash.
- Login e emissão de token JWT com validade de uma hora.
- Consulta do perfil do estudante autenticado.
- Salvamento do resultado e das respostas de um simulado.
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
  }
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

## Integração com o frontend

O cliente da API está em [`src/js/api.js`](../simu-oab-frontend/src/js/api.js). Atualmente, ele chama o backend publicado em `https://danilloteod.pythonanywhere.com` para:

| Ação no frontend | Requisição |
| --- | --- |
| Cadastro | `POST /api/cadastro` |
| Login | `POST /api/login` |
| Salvar resultado | `POST /api/simulados/salvar` |

Após o login, o frontend guarda o JWT em `localStorage` na chave `token_oab` e o nome em `user_name`. Ao salvar um simulado, envia o JWT como `Bearer` e o objeto com `edition`, `total_questions`, `score` e `answers`. O frontend só tenta salvar o resultado quando encontra um token.

Para testar com o backend local, altere temporariamente a URL base usada nessas chamadas no frontend para `http://127.0.0.1:5000`. As questões continuam sendo carregadas separadamente pelo frontend a partir de `/data/questoes_oab_<edição>_tipo1.json`.

O backend habilita CORS globalmente. Para uma implantação pública, restrinja as origens permitidas aos domínios do frontend.

## Testes

As dependências incluem `pytest`; execute a suíte com:

```bash
pytest
```

O teste atual em `test_.py` ainda usa a rota antiga `/api/tentativa/` e importa `app` em vez de usar a fábrica `create_app`; ele precisa ser atualizado para validar as rotas atuais.
