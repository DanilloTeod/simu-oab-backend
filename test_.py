import pytest
from app import app

@pytest.fixture
def client():
    """Cria um cliente de teste do Flask configurado em modo de teste."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_sucesso_dados_completos(client):
    payload = {"edition": "39",
                "total_questions": 25,
                "score": 6,
                "answers": [1, "a", "b"]
                }
    
    resposta = client.post('/api/tentativa/', json=payload)
    
    assert resposta.status_code == 200
    assert resposta.get_json()["response"] == "Simulado guardado com sucesso!"

