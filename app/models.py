from app.extensions import db # importa o db
from datetime import datetime, timezone 

# biblioteca do flask para criptografar senhas
from werkzeug.security import generate_password_hash, check_password_hash

class Estudante(db.Model): # tabela estudante

    # criação da chave primaria 
    id = db.Column(db.Integer, primary_key=True)

    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)

    # salvando a senha hash
    senha_hash = db.Column(db.String(255), nullable=False)

    # Relacionamento (A "mágica" para buscar os simulados do aluno depois)
    # um estudante tem vários simulados, O 'backref' cria uma propriedade
    # invisível lá no simulado chamada 'estudante', para você saber de quem é a prova.
    simulados = db.relationship('ResultadoSimulado', backref='estudante', lazy=True)

    # metodos da classe
    def set_senha(self, senha_pura): # recebe a senha pura(digitada) e transforma em um hash
        self.senha_hash = generate_password_hash(senha_pura) 

    def verificar_senha(self, senha_pura): # compara os hash's 
        return check_password_hash(self.senha_hash, senha_pura)

class ResultadoSimulado(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # db.ForeignKey('estudante.id') relaciona o id às duas tabelas
    estudante_id = db.Column(db.Integer, db.ForeignKey('estudante.id'), nullable=False)
    edicao_prova = db.Column(db.Integer, nullable=False)
    questoes_totais = db.Column(db.Integer, nullable=False)
    questoes_corretas = db.Column(db.Integer, nullable=False)

    """ 
    vem do front
    {
    question_id: questao.id,   // Ex: 1
    subject: questao.materia,         // Ex: a matéria da questão
    selected_option: choice, // Ex: "a"
    is_correct: acertou   // ou false (calculado no front-end se acertou ou errou)
    };
    
    """
    respostas_marcadas = db.Column(db.JSON, nullable=False)
    data_envio = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    