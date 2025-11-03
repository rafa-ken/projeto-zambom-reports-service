# app.py
import os
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument
from flask_cors import CORS
from auth import requires_auth, register_auth_error_handlers

load_dotenv()

app = Flask(__name__)
CORS(app, origins=os.getenv("FRONTEND_ORIGINS", "*"))

app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/reportsdb")
mongo = PyMongo(app)

register_auth_error_handlers(app)

@app.route("/reports", methods=["GET"])
@requires_auth()  # exige token para listar
def listar_reports():
    reports = mongo.db.reports.find()
    saida = []
    for report in reports:
        saida.append({
            "id": str(report["_id"]),
            "titulo": report.get("titulo"),
            "conteudo": report.get("conteudo"),
            "criado_em": report.get("criado_em").isoformat() if report.get("criado_em") else None,
            "atualizado_em": report.get("atualizado_em").isoformat() if report.get("atualizado_em") else None
        })
    return jsonify(saida), 200

@app.route("/reports", methods=["POST"])
@requires_auth(required_scope="create:reports")
def criar_report():
    dados = request.json
    if not dados or "titulo" not in dados or "conteudo" not in dados:
        return jsonify({"erro": "Campos 'titulo' e 'conteudo' são obrigatórios"}), 400

    agora = datetime.utcnow()
    report = {
        "titulo": dados["titulo"],
        "conteudo": dados["conteudo"],
        "criado_em": agora,
        "atualizado_em": agora
    }
    report_id = mongo.db.reports.insert_one(report).inserted_id

    return jsonify({
        "id": str(report_id),
        "titulo": report["titulo"],
        "conteudo": report["conteudo"],
        "criado_em": agora.isoformat(),
        "atualizado_em": agora.isoformat()
    }), 201

@app.route("/reports/<id>", methods=["PUT"])
@requires_auth(required_scope="update:reports")
def atualizar_report(id):
    try:
        _id = ObjectId(id)
    except InvalidId:
        return jsonify({"erro": "ID inválido"}), 400

    dados = request.json or {}
    agora = datetime.utcnow()
    atualizado = mongo.db.reports.find_one_and_update(
        {"_id": _id},
        {"$set": {
            "titulo": dados.get("titulo"),
            "conteudo": dados.get("conteudo"),
            "atualizado_em": agora
        }},
        return_document=ReturnDocument.AFTER
    )
    if not atualizado:
        return jsonify({"erro": "Relatório não encontrado"}), 404
    return jsonify({
        "id": str(atualizado["_id"]),
        "titulo": atualizado["titulo"],
        "conteudo": atualizado["conteudo"],
        "criado_em": atualizado.get("criado_em").isoformat() if atualizado.get("criado_em") else None,
        "atualizado_em": atualizado.get("atualizado_em").isoformat() if atualizado.get("atualizado_em") else None
    }), 200

@app.route("/reports/<id>", methods=["DELETE"])
@requires_auth(required_scope="delete:reports")
def deletar_report(id):
    try:
        _id = ObjectId(id)
    except InvalidId:
        return jsonify({"erro": "ID inválido"}), 400

    resultado = mongo.db.reports.delete_one({"_id": _id})
    if resultado.deleted_count == 0:
        return jsonify({"erro": "Relatório não encontrado"}), 404
    return jsonify({"mensagem": "Relatório deletado com sucesso"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5001)), debug=True)
