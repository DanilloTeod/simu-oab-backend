from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager

# o arquivo serve para criar as variaveis vazias das extensões

db = SQLAlchemy()
jwt = JWTManager()
