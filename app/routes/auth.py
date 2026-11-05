
import os
import re
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token,
    get_jwt,
    jwt_required,
    get_jwt_identity,
)
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import Estudante


auth_bp = Blueprint("auth", __name__)
RESET_TOKEN_MAX_AGE = 60 * 60
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESET_REQUEST_RESPONSE = {
    "mensagem": (
        "Se a conta estiver cadastrada, você receberá um email "
        "com instruções para redefinir a senha."
    )
}


def _serializador_redefinicao():
    return URLSafeTimedSerializer(
        current_app.config["JWT_SECRET_KEY"],
        salt="password-reset",
    )


def _token_de_redefinicao(estudante):
    return _serializador_redefinicao().dumps({
        "estudante_id": estudante.id,
        "auth_version": estudante.auth_version,
    })


def _enviar_email_redefinicao(email, token):
    configuracao = {
        "host": os.getenv("SMTP_HOST"),
        "username": os.getenv("SMTP_USERNAME"),
        "password": os.getenv("SMTP_PASSWORD"),
        "mail_from": os.getenv("MAIL_FROM"),
        "frontend_url": os.getenv("FRONTEND_URL"),
    }
    ausentes = [
        nome for nome, valor in configuracao.items()
        if not valor or not valor.strip()
    ]
    if ausentes:
        raise RuntimeError(
            "Configuração SMTP incompleta; defina: "
            + ", ".join(sorted(ausentes))
        )

    try:
        porta = int(os.getenv("SMTP_PORT", "587"))
    except ValueError as erro:
        raise RuntimeError("SMTP_PORT deve ser um inteiro válido.") from erro
    if not 1 <= porta <= 65535:
        raise RuntimeError("SMTP_PORT deve estar entre 1 e 65535.")

    tls_config = os.getenv("SMTP_USE_TLS", "true").strip().lower()
    if tls_config not in {"true", "1", "yes", "on", "false", "0", "no", "off"}:
        raise RuntimeError("SMTP_USE_TLS deve ser um valor booleano.")
    usar_tls = tls_config in {"true", "1", "yes", "on"}

    frontend_url = configuracao["frontend_url"].rstrip("/")
    reset_url = f"{frontend_url}/?{urlencode({'reset_token': token})}"
    mensagem = EmailMessage()
    mensagem["Subject"] = "Redefinição de senha"
    mensagem["From"] = configuracao["mail_from"]
    mensagem["To"] = email
    mensagem.set_content(
        "Recebemos uma solicitação para redefinir sua senha. "
        f"Use este link em até uma hora: {reset_url}\n\n"
        "Se você não solicitou a redefinição, ignore este email."
    )

    with smtplib.SMTP(configuracao["host"], porta, timeout=10) as servidor:
        if usar_tls:
            servidor.starttls(context=ssl.create_default_context())
        servidor.login(configuracao["username"], configuracao["password"])
        servidor.send_message(mensagem)


def email_configurado_como_admin(email):
    emails_admin = {
        item.strip().lower()
        for item in os.getenv("ADMIN_EMAILS", "").split(",")
        if item.strip()
    }
    return email.strip().lower() in emails_admin


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

    if len(nome) > 120 or len(email) > 150:
        return jsonify({"erro": "Nome ou email excede o tamanho permitido."}), 400

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

    if (
        not estudante
        or estudante.is_deleted
        or not estudante.verificar_senha(senha)
    ):
        return jsonify({
            "erro": "Email ou senha incorretos."
        }), 401

    if email_configurado_como_admin(estudante.email) and not estudante.is_admin:
        estudante.is_admin = True
    estudante.last_activity_at = datetime.now(timezone.utc)
    db.session.commit()

    token = create_access_token(
        identity=str(estudante.id),
        additional_claims={"auth_version": estudante.auth_version},
    )

    return jsonify({
        "mensagem": "Login aprovado",
        "token": token,
        "estudante": {
            "id": estudante.id,
            "nome": estudante.nome,
        },
        "is_admin": estudante.is_admin,
    }), 200


@auth_bp.route("/api/sessao/atividade", methods=["POST"])
@jwt_required()
def registrar_atividade_sessao():
    expira_em = datetime.fromtimestamp(get_jwt()["exp"], timezone.utc)
    resposta = {"mensagem": "Atividade registrada."}
    if expira_em - datetime.now(timezone.utc) < timedelta(days=7):
        estudante = db.session.get(Estudante, int(get_jwt_identity()))
        resposta["token"] = create_access_token(
            identity=str(estudante.id),
            additional_claims={"auth_version": estudante.auth_version},
        )
    return jsonify(resposta), 200


# Perfil protegido: exige token JWT
@auth_bp.route("/api/perfil", methods=["GET"])
@jwt_required()
def perfil():
    estudante_id = get_jwt_identity()

    estudante = db.session.get(
        Estudante, int(estudante_id)
    )

    if not estudante or estudante.is_deleted:
        return jsonify({
            "erro": "Estudante não encontrado."
        }), 404

    return jsonify({
        "id": estudante.id,
        "nome": estudante.nome,
        "email": estudante.email,
        "is_admin": estudante.is_admin,
    }), 200


@auth_bp.route("/api/password/forgot", methods=["POST"])
@auth_bp.route("/api/senha/recuperar", methods=["POST"])
def solicitar_redefinicao_senha():
    dados = request.get_json(silent=True)
    email = dados.get("email") if isinstance(dados, dict) else None
    if not isinstance(email, str) or not email.strip():
        return jsonify(RESET_REQUEST_RESPONSE), 200

    email = email.strip().lower()
    estudante = Estudante.query.filter_by(email=email).first()
    if not estudante or estudante.is_deleted:
        return jsonify(RESET_REQUEST_RESPONSE), 200

    try:
        _enviar_email_redefinicao(
            estudante.email,
            _token_de_redefinicao(estudante),
        )
    except Exception:
        current_app.logger.exception(
            "Falha ao enviar email de redefinição de senha. "
            "Verifique SMTP_HOST, SMTP_PORT, SMTP_USERNAME, "
            "SMTP_PASSWORD, SMTP_USE_TLS, MAIL_FROM e FRONTEND_URL."
        )

    return jsonify(RESET_REQUEST_RESPONSE), 200


@auth_bp.route("/api/password/reset", methods=["POST"])
@auth_bp.route("/api/senha/redefinir", methods=["POST"])
def redefinir_senha():
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({"erro": "Informe token e nova senha."}), 400

    token = dados.get("token")
    senha = dados.get("senha")
    if not isinstance(token, str) or not token:
        return jsonify({"erro": "Token inválido ou expirado."}), 400
    if not isinstance(senha, str) or len(senha) < 8:
        return jsonify({
            "erro": "A senha deve ter pelo menos 8 caracteres."
        }), 400

    try:
        conteudo = _serializador_redefinicao().loads(
            token,
            max_age=RESET_TOKEN_MAX_AGE,
        )
    except (BadSignature, SignatureExpired):
        return jsonify({"erro": "Token inválido ou expirado."}), 400

    if not isinstance(conteudo, dict):
        return jsonify({"erro": "Token inválido ou expirado."}), 400
    estudante_id = conteudo.get("estudante_id")
    auth_version = conteudo.get("auth_version")
    if type(estudante_id) is not int or type(auth_version) is not int:
        return jsonify({"erro": "Token inválido ou expirado."}), 400

    estudante = db.session.get(Estudante, estudante_id)
    if (
        not estudante
        or estudante.is_deleted
        or estudante.auth_version != auth_version
    ):
        return jsonify({"erro": "Token inválido ou expirado."}), 400

    atualizado = db.session.execute(
        update(Estudante)
        .where(
            Estudante.id == estudante.id,
            Estudante.auth_version == auth_version,
            Estudante.is_deleted.is_(False),
        )
        .values(
            senha_hash=generate_password_hash(senha),
            auth_version=Estudante.auth_version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if atualizado.rowcount != 1:
        db.session.rollback()
        return jsonify({"erro": "Token inválido ou expirado."}), 400
    db.session.commit()
    return jsonify({
        "mensagem": "Senha redefinida com sucesso. Faça login novamente."
    }), 200


@auth_bp.route("/api/perfil", methods=["PATCH"])
@jwt_required()
def editar_perfil():
    dados = request.get_json(silent=True)
    campos_permitidos = {"nome", "email", "senha_atual", "nova_senha"}
    if not isinstance(dados, dict) or not dados:
        return jsonify({"erro": "Informe os dados do perfil em formato JSON."}), 400
    if not set(dados).issubset(campos_permitidos):
        return jsonify({"erro": "A solicitação contém campos não permitidos."}), 400
    if "senha_atual" not in dados:
        return jsonify({
            "erro": "Informe a senha atual para atualizar o perfil."
        }), 400
    if not ({"nome", "email", "nova_senha"} & set(dados)):
        return jsonify({"erro": "Informe ao menos um dado para atualizar."}), 400
    if not isinstance(dados["senha_atual"], str):
        return jsonify({"erro": "Senha atual incorreta."}), 401

    estudante = db.session.get(Estudante, int(get_jwt_identity()))
    if not estudante or estudante.is_deleted:
        return jsonify({"erro": "Estudante não encontrado."}), 404
    if not estudante.verificar_senha(dados["senha_atual"]):
        return jsonify({"erro": "Senha atual incorreta."}), 401

    if "nome" in dados:
        nome = dados["nome"]
        if (
            not isinstance(nome, str)
            or not nome.strip()
            or len(nome.strip()) > 120
        ):
            return jsonify({
                "erro": "Informe um nome válido de até 120 caracteres."
            }), 400
        estudante.nome = nome.strip()

    if "email" in dados:
        email = dados["email"]
        if (
            not isinstance(email, str)
            or not email.strip()
            or len(email.strip()) > 150
            or not EMAIL_PATTERN.fullmatch(email.strip())
        ):
            return jsonify({"erro": "Informe um email válido."}), 400
        email = email.strip().lower()
        duplicado = Estudante.query.filter(
            Estudante.email == email,
            Estudante.id != estudante.id,
        ).first()
        if duplicado:
            return jsonify({"erro": "Este email já está cadastrado."}), 409
        estudante.email = email

    if "nova_senha" in dados:
        senha = dados["nova_senha"]
        if not isinstance(senha, str) or len(senha) < 8:
            return jsonify({
                "erro": "A senha deve ter pelo menos 8 caracteres."
            }), 400
        estudante.set_senha(senha)

    estudante.last_activity_at = datetime.now(timezone.utc)
    estudante.auth_version += 1
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"erro": "Este email já está cadastrado."}), 409

    return jsonify({
        "estudante": {
            "id": estudante.id,
            "nome": estudante.nome,
            "email": estudante.email,
            "is_admin": estudante.is_admin,
        },
        "token": create_access_token(
            identity=str(estudante.id),
            additional_claims={"auth_version": estudante.auth_version},
        ),
    }), 200
