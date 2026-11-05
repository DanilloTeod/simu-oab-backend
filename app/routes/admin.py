import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import Estudante, Presenca, ResultadoSimulado


admin_bp = Blueprint("admin", __name__)
ONLINE_WINDOW = timedelta(minutes=2)
PRESENCE_RETENTION = timedelta(days=1)


def email_inicial_admin(email):
    emails = {
        item.strip().lower()
        for item in os.getenv("ADMIN_EMAILS", "").split(",")
        if item.strip()
    }
    return email.strip().lower() in emails


def estudante_atual():
    identidade = get_jwt_identity()
    try:
        return db.session.get(Estudante, int(identidade))
    except (TypeError, ValueError):
        return None


def exigir_admin():
    estudante = estudante_atual()
    if not estudante:
        return None, (jsonify({"erro": "Estudante não encontrado."}), 404)

    if estudante.is_deleted or not estudante.is_admin:
        return None, (jsonify({"erro": "Acesso restrito a administradores."}), 403)

    return estudante, None


@admin_bp.route("/api/presenca", methods=["POST"])
@jwt_required(optional=True)
def registrar_presenca():
    dados = request.get_json(silent=True)
    session_id = dados.get("session_id") if isinstance(dados, dict) else None
    if not isinstance(session_id, str):
        return jsonify({"erro": "Informe um identificador de sessão válido."}), 400

    try:
        session_id = str(UUID(session_id))
    except ValueError:
        return jsonify({"erro": "Informe um identificador de sessão válido."}), 400

    estudante_id = None
    identidade = get_jwt_identity()
    if identidade is not None:
        try:
            estudante_id = int(identidade)
        except (TypeError, ValueError):
            return jsonify({"erro": "Token de estudante inválido."}), 401

    agora = datetime.now(timezone.utc)
    presenca = db.session.get(Presenca, session_id)
    if presenca is None:
        presenca = Presenca(session_id=session_id)
        db.session.add(presenca)

    presenca.estudante_id = estudante_id
    presenca.ultima_atividade = agora
    db.session.query(Presenca).filter(
        Presenca.ultima_atividade < agora - PRESENCE_RETENTION
    ).delete(synchronize_session=False)
    db.session.commit()

    presencas_ativas = Presenca.query.filter(
        Presenca.ultima_atividade >= agora - ONLINE_WINDOW
    ).all()
    alunos_online = {
        presenca.estudante_id
        for presenca in presencas_ativas
        if presenca.estudante_id is not None
    }
    anonimos_online = sum(
        presenca.estudante_id is None for presenca in presencas_ativas
    )

    return jsonify({
        "mensagem": "Presença atualizada.",
        "online_students": len(alunos_online),
        "online_anonymous": anonimos_online,
        "online_total": len(alunos_online) + anonimos_online,
    }), 200


@admin_bp.route("/api/admin/dashboard", methods=["GET"])
@jwt_required()
def dashboard_admin():
    _, erro = exigir_admin()
    if erro:
        return erro

    agora = datetime.now(timezone.utc)
    limite_online = agora - ONLINE_WINDOW
    presencas_ativas = Presenca.query.filter(
        Presenca.ultima_atividade >= limite_online
    ).all()
    presencas_por_estudante = {}
    for presenca in presencas_ativas:
        if presenca.estudante_id is None:
            continue
        anterior = presencas_por_estudante.get(presenca.estudante_id)
        if anterior is None or presenca.ultima_atividade > anterior:
            presencas_por_estudante[presenca.estudante_id] = (
                presenca.ultima_atividade
            )
    anonimos_online = sum(
        presenca.estudante_id is None for presenca in presencas_ativas
    )

    estudantes = (
        Estudante.query
        .filter(Estudante.is_deleted.is_(False))
        .order_by(Estudante.nome.asc())
        .all()
    )
    simulados = (
        ResultadoSimulado.query
        .order_by(ResultadoSimulado.data_envio.desc())
        .all()
    )
    simulados_por_estudante = {}
    for simulado in simulados:
        simulados_por_estudante.setdefault(simulado.estudante_id, []).append({
            "id": simulado.id,
            "edition": simulado.edicao_prova,
            "total_questions": simulado.questoes_totais,
            "score": simulado.questoes_corretas,
            "answers": simulado.respostas_marcadas,
            "submitted_at": (
                simulado.data_envio.isoformat()
                if simulado.data_envio
                else None
            ),
        })

    return jsonify({
        "summary": {
            "total_students": len(estudantes),
            "total_simulations": len(simulados),
            "online_students": len(presencas_por_estudante),
            "online_anonymous": anonimos_online,
            "online_total": len(presencas_por_estudante) + anonimos_online,
            "online_window_seconds": int(ONLINE_WINDOW.total_seconds()),
        },
        "online_users": [
            {
                "id": estudante.id,
                "name": estudante.nome,
                "email": estudante.email,
                "is_admin": estudante.is_admin,
                "last_activity": presencas_por_estudante[
                    estudante.id
                ].isoformat(),
            }
            for estudante in estudantes
            if estudante.id in presencas_por_estudante
        ],
        "students": [
            {
                "id": estudante.id,
                "name": estudante.nome,
                "email": estudante.email,
                "is_admin": estudante.is_admin,
                "online": estudante.id in presencas_por_estudante,
                "simulations": simulados_por_estudante.get(estudante.id, []),
            }
            for estudante in estudantes
        ],
    }), 200


@admin_bp.route("/api/admin/users", methods=["POST"])
@jwt_required()
def criar_usuario_admin():
    _, erro = exigir_admin()
    if erro:
        return erro

    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({"erro": "Envie os dados em formato JSON."}), 400

    nome = dados.get("nome")
    email = dados.get("email")
    senha = dados.get("senha")
    is_admin = dados.get("is_admin", False)
    if not all(
        isinstance(campo, str) and campo.strip()
        for campo in (nome, email, senha)
    ):
        return jsonify({"erro": "Preencha nome, email e senha."}), 400
    if not isinstance(is_admin, bool):
        return jsonify({"erro": "A permissão de administrador é inválida."}), 400

    nome = nome.strip()
    email = email.strip().lower()
    if len(nome) > 120 or len(email) > 150 or "@" not in email or any(
        caractere.isspace() for caractere in email
    ):
        return jsonify({"erro": "Informe um nome e email válidos."}), 400
    if len(senha) < 8:
        return jsonify({
            "erro": "A senha deve ter pelo menos 8 caracteres."
        }), 400
    if Estudante.query.filter_by(email=email).first():
        return jsonify({"erro": "Este email já está cadastrado."}), 409

    estudante = Estudante(
        nome=nome,
        email=email,
        is_admin=is_admin,
    )
    estudante.set_senha(senha)
    db.session.add(estudante)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"erro": "Este email já está cadastrado."}), 409

    return jsonify({
        "mensagem": "Conta criada com sucesso.",
        "user": {
            "id": estudante.id,
            "name": estudante.nome,
            "email": estudante.email,
            "is_admin": estudante.is_admin,
        },
    }), 201


@admin_bp.route("/api/admin/users/<int:estudante_id>/role", methods=["PATCH"])
@jwt_required()
def atualizar_permissao_usuario(estudante_id):
    _, erro = exigir_admin()
    if erro:
        return erro

    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or not isinstance(dados.get("is_admin"), bool):
        return jsonify({
            "erro": "Informe is_admin como true ou false."
        }), 400

    estudante = db.session.get(Estudante, estudante_id)
    if not estudante or estudante.is_deleted:
        return jsonify({"erro": "Conta não encontrada."}), 404

    nova_permissao = dados["is_admin"]
    if estudante.is_admin and not nova_permissao and email_inicial_admin(
        estudante.email
    ):
        return jsonify({
            "erro": "Remova este email de ADMIN_EMAILS antes de retirar a permissão."
        }), 409
    if estudante.is_admin and not nova_permissao:
        total_administradores = Estudante.query.filter(
            Estudante.is_admin.is_(True),
            Estudante.is_deleted.is_(False),
        ).count()
        if total_administradores <= 1:
            return jsonify({
                "erro": "Não é possível remover o último administrador."
            }), 409

    estudante.is_admin = nova_permissao
    db.session.commit()
    return jsonify({
        "mensagem": "Permissão atualizada.",
        "is_admin": estudante.is_admin,
    }), 200


@admin_bp.route("/api/admin/users/<int:estudante_id>", methods=["DELETE"])
@jwt_required()
def excluir_usuario_admin(estudante_id):
    administrador, erro = exigir_admin()
    if erro:
        return erro

    if administrador.id == estudante_id:
        return jsonify({
            "erro": "Não é possível excluir a própria conta administrativa."
        }), 409

    estudante = db.session.get(Estudante, estudante_id)
    if not estudante or estudante.is_deleted:
        return jsonify({"erro": "Conta não encontrada."}), 404

    if email_inicial_admin(estudante.email):
        return jsonify({
            "erro": "Remova este email de ADMIN_EMAILS antes de excluir a conta."
        }), 409

    if estudante.is_admin:
        total_administradores = Estudante.query.filter(
            Estudante.is_admin.is_(True),
            Estudante.is_deleted.is_(False),
        ).count()
        if total_administradores <= 1:
            return jsonify({
                "erro": "Não é possível excluir o último administrador."
            }), 409

    db.session.query(Presenca).filter_by(
        estudante_id=estudante.id
    ).update({"estudante_id": None}, synchronize_session=False)
    estudante.nome = "Conta excluída"
    estudante.email = f"excluida-{estudante.id}@invalid.invalid"
    estudante.is_admin = False
    estudante.is_deleted = True
    estudante.set_senha(secrets.token_urlsafe(32))
    db.session.commit()

    return jsonify({
        "mensagem": (
            "Conta anonimizada e removida. Os simulados foram preservados "
            "sem dados pessoais."
        )
    }), 200


@admin_bp.route("/api/admin/users/<int:estudante_id>", methods=["PATCH"])
@jwt_required()
def editar_usuario_admin(estudante_id):
    _, erro = exigir_admin()
    if erro:
        return erro

    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or not dados:
        return jsonify({"erro": "Informe os dados da conta em formato JSON."}), 400
    if not set(dados).issubset({"nome", "email", "senha"}):
        return jsonify({"erro": "A solicitação contém campos não permitidos."}), 400

    estudante = db.session.get(Estudante, estudante_id)
    if not estudante or estudante.is_deleted:
        return jsonify({"erro": "Conta não encontrada."}), 404

    if "nome" in dados:
        nome = dados["nome"]
        if not isinstance(nome, str) or not nome.strip() or len(nome.strip()) > 120:
            return jsonify({"erro": "Informe um nome válido de até 120 caracteres."}), 400
        estudante.nome = nome.strip()

    if "email" in dados:
        email = dados["email"]
        if (
            not isinstance(email, str)
            or not email.strip()
            or len(email.strip()) > 150
            or "@" not in email
            or any(caractere.isspace() for caractere in email)
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

    if "senha" in dados:
        senha = dados["senha"]
        if not isinstance(senha, str) or len(senha) < 8:
            return jsonify({
                "erro": "A senha deve ter pelo menos 8 caracteres."
            }), 400
        estudante.set_senha(senha)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"erro": "Este email já está cadastrado."}), 409

    return jsonify({
        "mensagem": "Dados da conta atualizados.",
        "user": {
            "id": estudante.id,
            "name": estudante.nome,
            "email": estudante.email,
        },
    }), 200
