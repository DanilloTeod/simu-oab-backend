
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import timedelta
import os

from app.extensions import db, jwt


load_dotenv()


def create_app():
    app = Flask(__name__)

    # Carrega a chave secreta do ambiente
    api_jwt_key = os.getenv("JWT_SECRET_KEY")

    if not api_jwt_key:
        raise RuntimeError(
            "JWT_SECRET_KEY não foi configurada no ambiente."
        )

    # Configurações básicas
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///banco_dados.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Configurações JWT
    app.config["JWT_SECRET_KEY"] = api_jwt_key
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
    app.config["JWT_TOKEN_LOCATION"] = ["headers"]

    # Permite a comunicação com o frontend
    CORS(app)

    # Inicializa as extensões
    db.init_app(app)
    jwt.init_app(app)

    # Registra as rotas
    from app.routes.auth import auth_bp
    from app.routes.simulados import simulados_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(simulados_bp)

    # Importa os modelos e cria as tabelas
    from app import models

    with app.app_context():
        db.create_all()

    return app
