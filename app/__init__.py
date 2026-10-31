
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import timedelta
import os
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
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
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

    return app
