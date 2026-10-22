
"""
Para o Python: Ele transforma a pasta app em um pacote importável, permitindo que o run.py 
(que está fora da pasta) consiga "enxergar" a função create_app.

"""

from flask import Flask

# importando as ferramentas
from app.extensions import db, jwt
from flask_cors import CORS # permite a conexao do frontend com backend
from dotenv import load_dotenv
import os

load_dotenv()
api_jwt_key=os.getenv("JWT_SECRET_KEY")

def create_app():
    app = Flask(__name__) # cria a instancia do Flask

    CORS(app)
    # definindo as configurações basicas
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///banco_dados.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JWT_SECRET_KEY'] = api_jwt_key

    # importa e registra as rotas de autenticação
    from app.routes.auth import auth_bp
    from app.routes.simulados import simulados_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(simulados_bp)

    # conectando as extensoes ao app
    db.init_app(app)
    jwt.init_app(app)

    from app import models
    with app.app_context():
        db.create_all()

    return app # retorna a aplicação final pronta