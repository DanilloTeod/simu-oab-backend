import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from app.extensions import db
from app.models import Estudante, Presenca, ResultadoSimulado


admin_bp = Blueprint("admin", __name__)
ONLINE_WINDOW = timedelta(minutes=2)
PRESENCE_RETENTION = timedelta(days=1)


def emails_administradores():
    return {
        email.strip().lower()
        for email in os.getenv("ADMIN_EMAILS", "").split(",")
        if email.strip()
    }


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

    if estudante.email.strip().lower() not in emails_administradores():
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
    alunos_online = {
        presenca.estudante_id
        for presenca in presencas_ativas
        if presenca.estudante_id is not None
    }
    anonimos_online = sum(
        presenca.estudante_id is None for presenca in presencas_ativas
    )

    estudantes = Estudante.query.order_by(Estudante.nome.asc()).all()
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
            "online_students": len(alunos_online),
            "online_anonymous": anonimos_online,
            "online_total": len(alunos_online) + anonimos_online,
            "online_window_seconds": int(ONLINE_WINDOW.total_seconds()),
        },
        "students": [
            {
                "id": estudante.id,
                "name": estudante.nome,
                "email": estudante.email,
                "simulations": simulados_por_estudante.get(estudante.id, []),
            }
            for estudante in estudantes
        ],
    }), 200
