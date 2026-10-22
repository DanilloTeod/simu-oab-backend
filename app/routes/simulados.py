from app.extensions import db # importa banco de dados
from flask_jwt_extended import jwt_required, get_jwt_identity # função que gera token jwt
from app.models import ResultadoSimulado
from flask import Blueprint, request, jsonify # importa blueprint (planta baixa)
                                            # agrupa rotas do mesmo assunto

simulados_bp = Blueprint('simulados', __name__)

@simulados_bp.route('/api/simulados/salvar', methods=['POST'])
@jwt_required() # Para salvar, preciso verificar se o aluno esta logado
def salvar_simulado():

    dados = request.get_json()

    # verificar quem é o estudante logado pelo token
    estudante_logado_id = int(get_jwt_identity())

    # valida os dados recebidos pelo frontend

    if (not dados or 'edition' not in 'answers' not in dados):
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


