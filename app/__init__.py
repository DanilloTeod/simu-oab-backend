
from flask import Flask, request
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import os
from sqlalchemy import inspect, text
from app.extensions import db, jwt

load_dotenv()


def create_app(test_config=None):
    app = Flask(__name__)

    api_jwt_key = (
        (test_config or {}).get("JWT_SECRET_KEY")
        or os.getenv("JWT_SECRET_KEY")
    )

    if not api_jwt_key:
        raise RuntimeError(
            "JWT_SECRET_KEY não foi configurada no ambiente."
        )

    # Configurações básicas
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "sqlite:///banco_dados.db",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Configurações JWT
    app.config["JWT_SECRET_KEY"] = api_jwt_key
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=30)
    app.config["JWT_TOKEN_LOCATION"] = ["headers"]

    if test_config:
        app.config.update(test_config)

    frontend_origins = [
        origin.strip()
        for origin in os.getenv(
            "FRONTEND_ORIGINS",
            (
                "http://localhost:5173,"
                "http://127.0.0.1:5173,"
                "https://simu-oab.vercel.app"
            ),
        ).split(",")
        if origin.strip()
    ]
    CORS(app, resources={r"/api/*": {"origins": frontend_origins}})

    # Inicializa as extensões
    db.init_app(app)
    jwt.init_app(app)

    # Registra as rotas
    from app.routes.auth import auth_bp
    from app.routes.admin import admin_bp
    from app.routes.simulados import simulados_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(simulados_bp)

    # Importa os modelos e cria as tabelas
    from app import models

    with app.app_context():
        db.create_all()
        _migrar_colunas_de_contas()
        _configurar_administradores_iniciais()

    @jwt.token_in_blocklist_loader
    def token_de_conta_excluida(jwt_header, jwt_payload):
        from app.models import Estudante

        try:
            estudante_id = int(jwt_payload["sub"])
        except (KeyError, TypeError, ValueError):
            return True

        estudante = db.session.get(Estudante, estudante_id)
        try:
            versao_token = int(jwt_payload["auth_version"])
        except (KeyError, TypeError, ValueError):
            return True

        if (
            estudante is None
            or estudante.is_deleted
            or estudante.auth_version != versao_token
        ):
            return True

        agora = datetime.now(timezone.utc)
        ultima_atividade = estudante.last_activity_at
        if ultima_atividade is None:
            return True
        if ultima_atividade.tzinfo is None:
            ultima_atividade = ultima_atividade.replace(tzinfo=timezone.utc)
        if agora - ultima_atividade >= timedelta(hours=1):
            return True

        if request.path not in {
            "/api/presenca",
            "/api/admin/dashboard",
        }:
            estudante.last_activity_at = agora
            db.session.commit()

        return False

    return app


def _migrar_colunas_de_contas():
    colunas = {
        coluna["name"]
        for coluna in inspect(db.engine).get_columns("estudante")
    }
    with db.engine.begin() as conexao:
        if "is_admin" not in colunas:
            conexao.execute(text(
                "ALTER TABLE estudante ADD COLUMN "
                "is_admin BOOLEAN NOT NULL DEFAULT 0"
            ))
        if "is_deleted" not in colunas:
            conexao.execute(text(
                "ALTER TABLE estudante ADD COLUMN "
                "is_deleted BOOLEAN NOT NULL DEFAULT 0"
            ))
        if "auth_version" not in colunas:
            conexao.execute(text(
                "ALTER TABLE estudante ADD COLUMN "
                "auth_version INTEGER NOT NULL DEFAULT 0"
            ))
        if "last_activity_at" not in colunas:
            conexao.execute(text(
                "ALTER TABLE estudante ADD COLUMN last_activity_at DATETIME"
            ))


def _configurar_administradores_iniciais():
    from app.models import Estudante

    emails = {
        email.strip().lower()
        for email in os.getenv("ADMIN_EMAILS", "").split(",")
        if email.strip()
    }
    if not emails:
        return

    Estudante.query.filter(
        db.func.lower(Estudante.email).in_(emails),
        Estudante.is_deleted.is_(False),
    ).update({Estudante.is_admin: True}, synchronize_session=False)
    db.session.commit()
