from app.extensions import db # importa banco de dados
from flask_jwt_extended import create_access_token # função que gera token jwt
from app.models import Estudante 
from flask import Blueprint, request, jsonify # importa blueprint (planta baixa)
                                            # agrupa rotas do mesmo assunto


auth_bp = Blueprint('auth', __name__) # criação do blueprint

# essa rota recebera o fetch do frontend 
"""
    vem do front
    {
    question_id: questao.id,   // Ex: 1
    subject: questao.materia,         // Ex: a matéria da questão
    selected_option: choice, // Ex: "a"
    is_correct: acertou   // ou false (calculado no front-end se acertou ou errou)
    };
"""
@auth_bp.route('/api/cadastro', methods=['POST'])
def cadastrar():
    dados = request.get_json()# pega os dados que o frontend enviou

    # Validações
    if (not dados.get('nome') or not dados.get('senha') 
        or not dados.get('senha')):
        return jsonify({"erro": "Preencha todos os campos!"}), 400

    if (Estudante.query.filter_by(email=dados['email']).first()):
        return jsonify({"erro": "Este email já está cadastrado."}), 400

    novo_estudante = Estudante(
        nome = dados.get('nome'),
        email = dados.get('email')
    )
    novo_estudante.set_senha(dados.get('senha')) # gera o hash para armazenar no db

    # salva no db 
    db.session.add(novo_estudante)
    db.session.commit()

    return jsonify({"mensagem": "Estudante cadastrado com sucesso!"}), 201

@auth_bp.route('/api/login', methods=['POST'])
def login():
    dados = request.get_json()

    estudante = Estudante.query.filter_by(email=dados.get('email')).first()

    # verifica se o estudante existe e se a senha bate com o hash
    if (estudante and estudante.verificar_senha(dados.get('senha'))):
        # Gera o Token JWT carimbando o ID do estudante escondido lá dentro
        token = create_access_token(identity=str(estudante.id))
        return jsonify({
            "mensagem": "Login aprovado",
            "token": token,
            "estudante": {
                "id": estudante.id,
                "nome": estudante.nome
            }
        }), 200

    return jsonify({"erro": "Email ou senha incorretos"}), 401



