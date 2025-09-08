import os
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from bson.objectid import ObjectId

# Carregar variáveis de ambiente
load_dotenv()

app = Flask(__name__)

# Configuração do MongoDB Atlas (ou local)
app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/reportsdb")
mongo = PyMongo(app)

# ---------------- ROTAS ---------------- #

# GET - Listar relatórios
@app.route("/reports", methods=["GET"])
def listar_reports():
    reports = mongo.db.reports.find()
    saida = []
    for report in reports:
        saida.append({
            "id": str(report["_id"]),
            "titulo": report["titulo"],
            "conteudo": report["conteudo"],
            "criado_em": report.get("criado_em"),
            "atualizado_em": report.get("atualizado_em")
        })
    return jsonify(saida), 200

# POST - Criar relatório
@app.route("/reports", methods=["POST"])
def criar_report():
    dados = request.json
    if not dados or "titulo" not in dados or "conteudo" not in dados:
        return jsonify({"erro": "Campos 'titulo' e 'conteudo' são obrigatórios"}), 400

    agora = datetime.utcnow()
    report_id = mongo.db.reports.insert_one({
        "titulo": dados["titulo"],
        "conteudo": dados["conteudo"],
        "criado_em": agora,
        "atualizado_em": agora
    }).inserted_id

    return jsonify({
        "id": str(report_id),
        "titulo": dados["titulo"],
        "conteudo": dados["conteudo"],
        "criado_em": agora.isoformat(),
        "atualizado_em": agora.isoformat()
    }), 201

# PUT - Atualizar relatório
@app.route("/reports/<id>", methods=["PUT"])
def atualizar_report(id):
    dados = request.json
    agora = datetime.utcnow()
    atualizado = mongo.db.reports.find_one_and_update(
        {"_id": ObjectId(id)},
        {"$set": {
            "titulo": dados.get("titulo"),
            "conteudo": dados.get("conteudo"),
            "atualizado_em": agora
        }},
        return_document=True
    )
    if not atualizado:
        return jsonify({"erro": "Relatório não encontrado"}), 404
    return jsonify({
        "id": str(atualizado["_id"]),
        "titulo": atualizado["titulo"],
        "conteudo": atualizado["conteudo"],
        "criado_em": atualizado.get("criado_em"),
        "atualizado_em": atualizado.get("atualizado_em")
    }), 200

# DELETE - Remover relatório
@app.route("/reports/<id>", methods=["DELETE"])
def deletar_report(id):
    resultado = mongo.db.reports.delete_one({"_id": ObjectId(id)})
    if resultado.deleted_count == 0:
        return jsonify({"erro": "Relatório não encontrado"}), 404
    return jsonify({"mensagem": "Relatório deletado com sucesso"}), 200

# --------------------------------------- #

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
