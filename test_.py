import pytest
from flask_jwt_extended import create_access_token

from app import create_app
from app.extensions import db
from app.models import Estudante, Presenca, ResultadoSimulado


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setenv(
        "FRONTEND_ORIGINS",
        "https://simu-oab.vercel.app,http://localhost:5173",
    )
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "JWT_SECRET_KEY": "test-key-long-enough-for-hmac-sha256",
    })

    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = Estudante(nome="Admin", email="admin@example.com")
        admin.set_senha("senha-de-teste")
        estudante = Estudante(nome="Aluna", email="aluna@example.com")
        estudante.set_senha("senha-de-teste")
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
        return create_access_token(identity=str(estudante_id))


def test_login_identifica_administrador(client):
    resposta = client.post("/api/login", json={
        "email": "admin@example.com",
        "senha": "senha-de-teste",
    })

    assert resposta.status_code == 200
    assert resposta.get_json()["is_admin"] is True


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
