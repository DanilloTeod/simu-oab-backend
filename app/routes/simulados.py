from app.extensions import db # importa banco de dados
from flask_jwt_extended import jwt_required, get_jwt_identity # função que gera token jwt
from app.models import ResultadoSimulado
from flask import Blueprint, request, jsonify # importa blueprint (planta baixa)
                                            # agrupa rotas do mesmo assunto

simulados_bp = Blueprint('simulados', __name__)

@simulados_bp.route('/api/simulados/salvar', methods=['POST'])
@jwt_required() # Para salvar, preciso verificar se o aluno esta logado
def salvar_simulado():

    dados = request.get_json(silent=True)

    # verificar quem é o estudante logado pelo token
    estudante_logado_id = int(get_jwt_identity())

    # valida os dados recebidos pelo frontend

    campos_obrigatorios = {
        'edition',
        'total_questions',
        'score',
        'answers',
    }
    if not isinstance(dados, dict) or not campos_obrigatorios.issubset(dados):
        return jsonify({"erro": "Dados do simulado incompletos."}), 400

    try:
        dados_simulado = ResultadoSimulado(
            estudante_id=estudante_logado_id,
            edicao_prova=dados['edition'],
            questoes_totais=dados['total_questions'],
            questoes_corretas=dados['score'],
            respostas_marcadas=dados['answers']
        )
        db.session.add(dados_simulado) # coloca na fila de salvamentos do db
        db.session.commit()
        return jsonify({"mensagem": "Simulado salvo com sucesso!",
                        "resultado_id": dados_simulado.id
                        }), 201

    except Exception as erro:
        db.session.rollback() # Desfaz tudo que estava na fila, caso dê algo errado
        return jsonify({
            "erro": "Falha ao salvar o simulado",
            "detalhes": str(erro)
        }), 500

@simulados_bp.route('/api/simulados/historico', methods=['GET'])
@jwt_required()
def historico():
    estudante_id_logado = int(get_jwt_identity())

    simulados_estudante = (
        ResultadoSimulado.query
        .filter_by(estudante_id=estudante_id_logado)
        .order_by(ResultadoSimulado.data_envio.desc())
        .all()
    )

    historico_serializado = [
        {
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
        }
        for simulado in simulados_estudante
    ]

    return jsonify(historico_serializado), 200