import sqlite3
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock

import pytest
from flask_jwt_extended import create_access_token
from itsdangerous import URLSafeTimedSerializer

from app import create_app
from app.extensions import db
from app.models import Estudante, Presenca, ResultadoSimulado
from app.routes import auth


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setenv("PERSONAL_THEME_STUDENT_IDS", "")
    monkeypatch.setenv(
        "FRONTEND_ORIGINS",
        "https://simu-oab.vercel.app,http://localhost:5173",
    )
    monkeypatch.setenv("SMTP_HOST", "smtp.test.invalid")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "test-user")
    monkeypatch.setenv("SMTP_PASSWORD", "test-password")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setenv("MAIL_FROM", "noreply@example.com")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173")
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "JWT_SECRET_KEY": "test-key-long-enough-for-hmac-sha256",
        "FRONTEND_URL": "http://localhost:5173",
    })

    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = Estudante(
            nome="Admin",
            email="admin@example.com",
            is_admin=True,
        )
        admin.set_senha("senha-de-teste")
        estudante = Estudante(nome="Aluna", email="aluna@example.com")
        estudante.set_senha("senha-de-teste")
        agora = datetime.now(timezone.utc)
        admin.last_activity_at = agora
        estudante.last_activity_at = agora
        db.session.add_all([admin, estudante])
        db.session.flush()
        db.session.add(ResultadoSimulado(
            estudante_id=estudante.id,
            edicao_prova=47,
            questoes_totais=1,
            questoes_corretas=1,
            respostas_marcadas=[{
                "question_id": 1,
                "subject": "etica",
                "selected_option": "a",
                "is_correct": True,
            }],
        ))
        db.session.commit()
        app.config["TEST_ADMIN_ID"] = admin.id
        app.config["TEST_STUDENT_ID"] = estudante.id

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def token_para(app, estudante_id):
    with app.app_context():
        estudante = db.session.get(Estudante, estudante_id)
        return create_access_token(
            identity=str(estudante_id),
            additional_claims={"auth_version": estudante.auth_version},
        )


def token_redefinicao_para(app, estudante_id):
    with app.app_context():
        estudante = db.session.get(Estudante, estudante_id)
        return URLSafeTimedSerializer(
            app.config["JWT_SECRET_KEY"],
            salt="password-reset",
        ).dumps({
            "estudante_id": estudante.id,
            "auth_version": estudante.auth_version,
        })


def smtp_mock(monkeypatch, error=None):
    servidor = MagicMock()
    servidor_cm = MagicMock()
    servidor_cm.__enter__.return_value = servidor
    servidor_cm.__exit__.return_value = False
    fabrica = MagicMock(return_value=servidor_cm)
    if error:
        fabrica.side_effect = error
    monkeypatch.setattr(auth.smtplib, "SMTP", fabrica)
    return fabrica, servidor


def test_login_identifica_administrador(client):
    resposta = client.post("/api/login", json={
        "email": "admin@example.com",
        "senha": "senha-de-teste",
    })

    assert resposta.status_code == 200
    assert resposta.get_json()["is_admin"] is True
    assert resposta.get_json()["can_use_personal_theme"] is True
    with client.application.app_context():
        administrador = db.session.get(
            Estudante,
            client.application.config["TEST_ADMIN_ID"],
        )
        assert administrador.last_activity_at is not None


def test_tema_pessoal_depende_do_id_autorizado_no_backend(client, app):
    estudante_id = app.config["TEST_STUDENT_ID"]
    app.config["PERSONAL_THEME_STUDENT_IDS"] = frozenset({estudante_id})
    with app.app_context():
        estudante = db.session.get(Estudante, estudante_id)
        estudante.nome = "Aluna com nome não relacionado à permissão"
        db.session.commit()

    resposta_login = client.post("/api/login", json={
        "email": "aluna@example.com",
        "senha": "senha-de-teste",
    })

    assert resposta_login.status_code == 200
    assert resposta_login.get_json()["can_use_personal_theme"] is True
    token = resposta_login.get_json()["token"]
    resposta_perfil = client.get(
        "/api/perfil",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resposta_perfil.get_json()["can_use_personal_theme"] is True

    app.config["PERSONAL_THEME_STUDENT_IDS"] = frozenset()
    resposta_sem_permissao = client.get(
        "/api/perfil",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resposta_sem_permissao.get_json()["can_use_personal_theme"] is False


def test_tema_pessoal_nao_e_concedido_apenas_por_nome(client, app):
    estudante_id = app.config["TEST_STUDENT_ID"]
    app.config["PERSONAL_THEME_STUDENT_IDS"] = frozenset()
    with app.app_context():
        estudante = db.session.get(Estudante, estudante_id)
        estudante.nome = "Aluna autorizada somente pelo identificador"
        db.session.commit()

    resposta = client.post("/api/login", json={
        "email": "aluna@example.com",
        "senha": "senha-de-teste",
    })

    assert resposta.status_code == 200
    assert resposta.get_json()["can_use_personal_theme"] is False


def test_sessao_expira_apos_uma_hora_sem_atividade(client, app):
    estudante_id = app.config["TEST_STUDENT_ID"]
    with app.app_context():
        estudante = db.session.get(Estudante, estudante_id)
        estudante.last_activity_at = (
            datetime.now(timezone.utc) - timedelta(hours=1, seconds=1)
        )
        db.session.commit()

    resposta = client.get(
        "/api/simulados/historico",
        headers={"Authorization": f"Bearer {token_para(app, estudante_id)}"},
    )

    assert resposta.status_code == 401


def test_atividade_autenticada_renova_sessao(client, app):
    estudante_id = app.config["TEST_STUDENT_ID"]
    with app.app_context():
        estudante = db.session.get(Estudante, estudante_id)
        estudante.last_activity_at = (
            datetime.now(timezone.utc) - timedelta(minutes=55)
        )
        db.session.commit()

    resposta = client.post(
        "/api/sessao/atividade",
        headers={"Authorization": f"Bearer {token_para(app, estudante_id)}"},
    )

    assert resposta.status_code == 200
    assert "token" not in resposta.get_json()
    with app.app_context():
        estudante = db.session.get(Estudante, estudante_id)
        ultima_atividade = estudante.last_activity_at
        if ultima_atividade.tzinfo is None:
            ultima_atividade = ultima_atividade.replace(tzinfo=timezone.utc)
        assert datetime.now(timezone.utc) - ultima_atividade < timedelta(seconds=5)


def test_atividade_renova_jwt_proximo_da_expiracao(client, app):
    estudante_id = app.config["TEST_STUDENT_ID"]
    with app.app_context():
        estudante = db.session.get(Estudante, estudante_id)
        token = create_access_token(
            identity=str(estudante_id),
            additional_claims={"auth_version": estudante.auth_version},
            expires_delta=timedelta(days=1),
        )

    resposta = client.post(
        "/api/sessao/atividade",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 200
    assert resposta.get_json()["token"] != token


def test_heartbeat_de_presenca_nao_renova_sessao_inativa(client, app):
    estudante_id = app.config["TEST_STUDENT_ID"]
    atividade_anterior = datetime.now(timezone.utc) - timedelta(minutes=50)
    with app.app_context():
        estudante = db.session.get(Estudante, estudante_id)
        estudante.last_activity_at = atividade_anterior
        db.session.commit()

    resposta = client.post(
        "/api/presenca",
        json={"session_id": "00000000-0000-0000-0000-000000000005"},
        headers={"Authorization": f"Bearer {token_para(app, estudante_id)}"},
    )

    assert resposta.status_code == 200
    with app.app_context():
        estudante = db.session.get(Estudante, estudante_id)
        ultima_atividade = estudante.last_activity_at
        if ultima_atividade.tzinfo is None:
            ultima_atividade = ultima_atividade.replace(tzinfo=timezone.utc)
        assert abs((ultima_atividade - atividade_anterior).total_seconds()) < 2


def test_solicitacao_redefinicao_nao_revela_se_email_existe(
    client, monkeypatch
):
    _, servidor = smtp_mock(monkeypatch)
    conhecida = client.post(
        "/api/senha/recuperar",
        json={"email": "aluna@example.com"},
    )
    desconhecida = client.post(
        "/api/senha/recuperar",
        json={"email": "nao-existe@example.com"},
    )

    assert conhecida.status_code == desconhecida.status_code == 200
    assert conhecida.get_json() == desconhecida.get_json()
    assert servidor.send_message.call_count == 1
    mensagem = servidor.send_message.call_args.args[0]
    assert mensagem["To"] == "aluna@example.com"
    url = re.search(r"http://\S+", mensagem.get_content()).group(0)
    parsed_url = urlparse(url)
    assert f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}" == (
        "http://localhost:5173/"
    )
    token = parse_qs(parsed_url.query)["reset_token"][0]
    assert client.post("/api/senha/redefinir", json={
        "token": token,
        "senha": "senha-nova-segura",
    }).status_code == 200


def test_falha_smtp_mantem_resposta_generica_e_registra_erro(
    client, monkeypatch, caplog
):
    smtp_mock(monkeypatch, error=OSError("smtp indisponível"))
    resposta = client.post(
        "/api/senha/recuperar",
        json={"email": "aluna@example.com"},
    )

    assert resposta.status_code == 200
    assert resposta.get_json() == {
        "mensagem": (
            "Se a conta estiver cadastrada, você receberá um email "
            "com instruções para redefinir a senha."
        )
    }
    assert "Verifique SMTP_HOST" in caplog.text


def test_smtp_nao_configurado_mantem_resposta_generica(
    client, monkeypatch, caplog
):
    fabrica, _ = smtp_mock(monkeypatch)
    monkeypatch.delenv("SMTP_HOST")
    resposta = client.post(
        "/api/senha/recuperar",
        json={"email": "aluna@example.com"},
    )

    assert resposta.status_code == 200
    assert resposta.get_json() == {
        "mensagem": (
            "Se a conta estiver cadastrada, você receberá um email "
            "com instruções para redefinir a senha."
        )
    }
    fabrica.assert_not_called()
    assert "Configuração SMTP incompleta" in caplog.text


def test_redefinicao_senha_token_valido_e_reutilizacao_rejeitada(
    client, app
):
    token = token_redefinicao_para(app, app.config["TEST_STUDENT_ID"])
    redefinida = client.post("/api/senha/redefinir", json={
        "token": token,
        "senha": "senha-nova-segura",
    })
    reutilizada = client.post("/api/senha/redefinir", json={
        "token": token,
        "senha": "outra-senha-segura",
    })

    assert redefinida.status_code == 200
    assert reutilizada.status_code == 400
    assert client.post("/api/login", json={
        "email": "aluna@example.com",
        "senha": "senha-de-teste",
    }).status_code == 401
    assert client.post("/api/login", json={
        "email": "aluna@example.com",
        "senha": "senha-nova-segura",
    }).status_code == 200


def test_redefinicao_senha_rejeita_token_expirado(
    client, app, monkeypatch
):
    token = token_redefinicao_para(app, app.config["TEST_STUDENT_ID"])
    monkeypatch.setattr(auth, "RESET_TOKEN_MAX_AGE", -1)

    resposta = client.post("/api/senha/redefinir", json={
        "token": token,
        "senha": "senha-nova-segura",
    })

    assert resposta.status_code == 400
    assert "Token inválido ou expirado" in resposta.get_json()["erro"]


def test_redefinicao_senha_exige_senha_minima(client, app):
    token = token_redefinicao_para(app, app.config["TEST_STUDENT_ID"])
    resposta = client.post("/api/senha/redefinir", json={
        "token": token,
        "senha": "curta",
    })

    assert resposta.status_code == 400
    assert "8 caracteres" in resposta.get_json()["erro"]


def test_estudante_atualiza_perfil_com_senha_atual_e_revoga_token(
    client, app
):
    estudante_id = app.config["TEST_STUDENT_ID"]
    token_antigo = token_para(app, estudante_id)
    resposta = client.patch(
        "/api/perfil",
        headers={"Authorization": f"Bearer {token_antigo}"},
        json={
            "nome": "Aluna Atualizada",
            "email": "aluna.nova@example.com",
            "nova_senha": "senha-nova-segura",
            "senha_atual": "senha-de-teste",
        },
    )

    assert resposta.status_code == 200
    assert resposta.get_json()["estudante"] == {
        "id": estudante_id,
        "nome": "Aluna Atualizada",
        "email": "aluna.nova@example.com",
        "is_admin": False,
    }
    assert client.get(
        "/api/perfil",
        headers={"Authorization": f"Bearer {token_antigo}"},
    ).status_code == 401
    token_novo = resposta.get_json()["token"]
    assert client.get(
        "/api/perfil",
        headers={"Authorization": f"Bearer {token_novo}"},
    ).status_code == 200
    assert client.post("/api/login", json={
        "email": "aluna.nova@example.com",
        "senha": "senha-nova-segura",
    }).status_code == 200


@pytest.mark.parametrize(
    ("dados", "status"),
    [
        ({"nome": "Nova"}, 400),
        ({"nome": "Nova", "senha_atual": "incorreta"}, 401),
        ({"email": "invalido", "senha_atual": "senha-de-teste"}, 400),
        (
            {"email": "admin@example.com", "senha_atual": "senha-de-teste"},
            409,
        ),
        (
            {
                "nova_senha": "curta",
                "senha_atual": "senha-de-teste",
            },
            400,
        ),
    ],
)
def test_edicao_perfil_rejeita_credencial_ou_dados_invalidos(
    client, app, dados, status
):
    token = token_para(app, app.config["TEST_STUDENT_ID"])
    resposta = client.patch(
        "/api/perfil",
        headers={"Authorization": f"Bearer {token}"},
        json=dados,
    )

    assert resposta.status_code == status


def test_historico_requer_login_e_retorna_apenas_resultados_do_aluno(client, app):
    sem_token = client.get("/api/simulados/historico")
    assert sem_token.status_code == 401

    token = token_para(app, app.config["TEST_STUDENT_ID"])
    resposta = client.get(
        "/api/simulados/historico",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 200
    assert len(resposta.get_json()) == 1
    assert resposta.get_json()[0]["edition"] == 47


def test_dashboard_admin_autorizado_e_rejeita_aluno_comum(client, app):
    admin_token = token_para(app, app.config["TEST_ADMIN_ID"])
    estudante_token = token_para(app, app.config["TEST_STUDENT_ID"])

    dashboard = client.get(
        "/api/admin/dashboard",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert dashboard.status_code == 200
    assert dashboard.get_json()["summary"]["total_students"] == 2
    assert dashboard.get_json()["summary"]["total_simulations"] == 1

    proibido = client.get(
        "/api/admin/dashboard",
        headers={"Authorization": f"Bearer {estudante_token}"},
    )
    assert proibido.status_code == 403


def test_admin_cria_conta_e_atualiza_permissao(client, app):
    admin_token = token_para(app, app.config["TEST_ADMIN_ID"])
    cabecalhos = {"Authorization": f"Bearer {admin_token}"}

    criada = client.post(
        "/api/admin/users",
        headers=cabecalhos,
        json={
            "nome": "Nova pessoa",
            "email": "nova@example.com",
            "senha": "senha-segura",
            "is_admin": False,
        },
    )
    assert criada.status_code == 201
    estudante_id = criada.get_json()["user"]["id"]

    promovida = client.patch(
        f"/api/admin/users/{estudante_id}/role",
        headers=cabecalhos,
        json={"is_admin": True},
    )
    assert promovida.status_code == 200

    login = client.post("/api/login", json={
        "email": "nova@example.com",
        "senha": "senha-segura",
    })
    assert login.status_code == 200
    assert login.get_json()["is_admin"] is True


def test_admin_nao_pode_remover_ultimo_administrador(
    client, app, monkeypatch
):
    monkeypatch.setenv("ADMIN_EMAILS", "")
    admin_token = token_para(app, app.config["TEST_ADMIN_ID"])
    resposta = client.patch(
        f"/api/admin/users/{app.config['TEST_ADMIN_ID']}/role",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"is_admin": False},
    )
    assert resposta.status_code == 409


def test_admin_edita_conta_e_redefine_senha(client, app):
    admin_token = token_para(app, app.config["TEST_ADMIN_ID"])
    estudante_id = app.config["TEST_STUDENT_ID"]
    resposta = client.patch(
        f"/api/admin/users/{estudante_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "nome": "Aluna Atualizada",
            "email": "atualizada@example.com",
            "senha": "nova-senha-segura",
        },
    )
    assert resposta.status_code == 200

    senha_antiga = client.post("/api/login", json={
        "email": "atualizada@example.com",
        "senha": "senha-de-teste",
    })
    senha_nova = client.post("/api/login", json={
        "email": "atualizada@example.com",
        "senha": "nova-senha-segura",
    })
    assert senha_antiga.status_code == 401
    assert senha_nova.status_code == 200


def test_exclusao_anonimiza_conta_preserva_simulados_e_revoga_token(
    client, app
):
    estudante_id = app.config["TEST_STUDENT_ID"]
    admin_token = token_para(app, app.config["TEST_ADMIN_ID"])
    estudante_token = token_para(app, estudante_id)
    with app.app_context():
        db.session.add(Presenca(
            session_id="00000000-0000-0000-0000-000000000005",
            estudante_id=estudante_id,
        ))
        db.session.commit()

    resposta = client.delete(
        f"/api/admin/users/{estudante_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resposta.status_code == 200

    with app.app_context():
        estudante = db.session.get(Estudante, estudante_id)
        assert estudante.is_deleted is True
        assert estudante.nome == "Conta excluída"
        assert estudante.email.endswith("@invalid.invalid")
        assert ResultadoSimulado.query.filter_by(
            estudante_id=estudante_id
        ).count() == 1
        presenca = db.session.get(
            Presenca, "00000000-0000-0000-0000-000000000005"
        )
        assert presenca.estudante_id is None

    historico = client.get(
        "/api/simulados/historico",
        headers={"Authorization": f"Bearer {estudante_token}"},
    )
    assert historico.status_code == 401

    painel = client.get(
        "/api/admin/dashboard",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert painel.status_code == 200
    assert painel.get_json()["summary"]["total_students"] == 1
    assert painel.get_json()["summary"]["total_simulations"] == 1


def test_dashboard_lista_identidade_das_contas_online(client, app):
    estudante_id = app.config["TEST_STUDENT_ID"]
    with app.app_context():
        db.session.add(Presenca(
            session_id="00000000-0000-0000-0000-000000000006",
            estudante_id=estudante_id,
        ))
        db.session.commit()

    token = token_para(app, app.config["TEST_ADMIN_ID"])
    resposta = client.get(
        "/api/admin/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )

    online = resposta.get_json()["online_users"]
    assert resposta.status_code == 200
    assert len(online) == 1
    assert online[0]["email"] == "aluna@example.com"
    assert online[0]["name"] == "Aluna"
    assert online[0]["last_activity"].endswith("+00:00")
    estudante = next(
        item for item in resposta.get_json()["students"]
        if item["email"] == "aluna@example.com"
    )
    assert estudante["last_access"].endswith("+00:00")
    assert estudante["simulations"][0]["submitted_at"].endswith("+00:00")


def test_presenca_conta_estudantes_e_sessoes_anonimas(client, app):
    estudante_id = app.config["TEST_STUDENT_ID"]
    with app.app_context():
        db.session.add_all([
            Presenca(
                session_id="00000000-0000-0000-0000-000000000001",
                estudante_id=estudante_id,
            ),
            Presenca(
                session_id="00000000-0000-0000-0000-000000000002",
                estudante_id=estudante_id,
            ),
            Presenca(
                session_id="00000000-0000-0000-0000-000000000004",
            ),
        ])
        db.session.commit()

    token = token_para(app, estudante_id)
    resposta = client.post(
        "/api/presenca",
        json={"session_id": "00000000-0000-0000-0000-000000000003"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 200
    assert resposta.get_json()["online_students"] == 1
    assert resposta.get_json()["online_anonymous"] == 1
    assert resposta.get_json()["online_total"] == 2


def test_salvar_simulado_persiste_resultado(client, app):
    token = token_para(app, app.config["TEST_STUDENT_ID"])
    resposta = client.post(
        "/api/simulados/salvar",
        json={
            "edition": 45,
            "total_questions": 1,
            "score": 0,
            "answers": [{
                "question_id": 2,
                "subject": "civil",
                "selected_option": "b",
                "is_correct": False,
            }],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 201
    assert resposta.get_json()["resultado_id"]


def test_cors_permite_preflight_da_vercel(client):
    resposta = client.options(
        "/api/presenca",
        headers={
            "Origin": "https://simu-oab.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert resposta.headers["Access-Control-Allow-Origin"] == (
        "https://simu-oab.vercel.app"
    )
    assert "POST" in resposta.headers["Access-Control-Allow-Methods"]


def test_migracao_adiciona_colunas_em_banco_existente(tmp_path, monkeypatch):
    database_path = tmp_path / "banco_antigo.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("""
            CREATE TABLE estudante (
                id INTEGER PRIMARY KEY,
                nome VARCHAR(120) NOT NULL,
                email VARCHAR(150) UNIQUE NOT NULL,
                senha_hash VARCHAR(255) NOT NULL
            )
        """)
        connection.execute(
            "INSERT INTO estudante (nome, email, senha_hash) "
            "VALUES (?, ?, ?)",
            ("Admin legado", "admin-legado@example.com", "hash"),
        )

    monkeypatch.setenv("ADMIN_EMAILS", "admin-legado@example.com")
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        "JWT_SECRET_KEY": "test-key-long-enough-for-hmac-sha256",
    })
    with app.app_context():
        estudante = db.session.get(Estudante, 1)
        assert estudante.is_admin is True
        assert estudante.is_deleted is False
        assert estudante.auth_version == 0
        assert estudante.last_activity_at is None
