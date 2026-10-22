
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity,
)
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Estudante


auth_bp = Blueprint("auth", __name__)


# Cadastro público
@auth_bp.route("/api/cadastro", methods=["POST"])
def cadastrar():
    dados = request.get_json(silent=True)

    if not isinstance(dados, dict):
        return jsonify({"erro": "Envie os dados em formato JSON."}), 400

    nome = dados.get("nome")
    email = dados.get("email")
    senha = dados.get("senha")

    if not all(
        isinstance(campo, str) and campo.strip()
        for campo in (nome, email, senha)
    ):
        return jsonify({"erro": "Preencha todos os campos!"}), 400

    nome = nome.strip()
    email = email.strip().lower()

    if len(senha) < 8:
        return jsonify({
            "erro": "A senha deve ter pelo menos 8 caracteres."
        }), 400

    if Estudante.query.filter_by(email=email).first():
        return jsonify({
            "erro": "Este email já está cadastrado."
        }), 409

    novo_estudante = Estudante(
        nome=nome,
        email=email,
    )
    novo_estudante.set_senha(senha)

    try:
        db.session.add(novo_estudante)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "erro": "Não foi possível cadastrar. Verifique se o email já existe."
        }), 409

    return jsonify({
        "mensagem": "Estudante cadastrado com sucesso!"
    }), 201


# Login público
@auth_bp.route("/api/login", methods=["POST"])
def login():
    dados = request.get_json(silent=True)

    if not isinstance(dados, dict):
        return jsonify({"erro": "Envie os dados em formato JSON."}), 400

    email = dados.get("email")
    senha = dados.get("senha")

    if not isinstance(email, str) or not isinstance(senha, str):
        return jsonify({"erro": "Informe email e senha."}), 400

    estudante = Estudante.query.filter_by(
        email=email.strip().lower()
    ).first()

    if not estudante or not estudante.verificar_senha(senha):
        return jsonify({
            "erro": "Email ou senha incorretos."
        }), 401

    token = create_access_token(
        identity=str(estudante.id)
    )

    return jsonify({
        "mensagem": "Login aprovado",
        "token": token,
        "estudante": {
            "id": estudante.id,
            "nome": estudante.nome,
        },
    }), 200


# Perfil protegido: exige token JWT
@auth_bp.route("/api/perfil", methods=["GET"])
@jwt_required()
def perfil():
    estudante_id = get_jwt_identity()

    estudante = db.session.get(
        Estudante, int(estudante_id)
    )

    if not estudante:
        return jsonify({
            "erro": "Estudante não encontrado."
        }), 404

    return jsonify({
        "id": estudante.id,
        "nome": estudante.nome,
        "email": estudante.email,
    }), 200
