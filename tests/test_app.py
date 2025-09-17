import pytest
import mongomock
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app, mongo

@pytest.fixture
def client():
    app.config["TESTING"] = True

    # Mocka o MongoDB em memória
    mongo.cx = mongomock.MongoClient()
    mongo.db = mongo.cx["reports_testdb"]

    client = app.test_client()
    yield client
    mongo.db.reports.delete_many({})

def test_criar_report(client):
    resposta = client.post("/reports", json={"titulo": "Relatório 1", "conteudo": "Primeiro relatório"})
    assert resposta.status_code == 201
    assert resposta.json["titulo"] == "Relatório 1"
    assert resposta.json["conteudo"] == "Primeiro relatório"

def test_listar_reports(client):
    client.post("/reports", json={"titulo": "Relatório 2", "conteudo": "Segundo relatório"})
    resposta = client.get("/reports")
    assert resposta.status_code == 200
    assert isinstance(resposta.json, list)
    assert len(resposta.json) > 0

def test_atualizar_report(client):
    resposta = client.post("/reports", json={"titulo": "Relatório Antigo", "conteudo": "Versão inicial"})
    report_id = resposta.json["id"]

    update_res = client.put(f"/reports/{report_id}", json={"titulo": "Relatório Atualizado", "conteudo": "Nova versão"})
    assert update_res.status_code == 200
    assert update_res.json["titulo"] == "Relatório Atualizado"
    assert update_res.json["conteudo"] == "Nova versão"

def test_deletar_report(client):
    resposta = client.post("/reports", json={"titulo": "Relatório Deletar", "conteudo": "Será removido"})
    report_id = resposta.json["id"]

    delete_res = client.delete(f"/reports/{report_id}")
    assert delete_res.status_code == 200
    assert delete_res.json["mensagem"] == "Relatório deletado com sucesso"
