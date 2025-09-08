import os
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from bson.objectid import ObjectId

# Carregar variáveis de ambiente
load_dotenv()

app = Flask(__name__)

# Configuração do MongoDB Atlas
app.config["MONGO_URI"] = os.getenv("MONGO_URI")  # ex: .../ZAMBOM
mongo = PyMongo(app)


# GET - Listar anotações
@app.route("/notes", methods=["GET"])
def listar_notes():
    notes = mongo.db.notes.find()
    saida = []
    for note in notes:
        saida.append({
            "id": str(note["_id"]),
            "titulo": note["titulo"],
            "conteudo": note["conteudo"],
            "criado_em": note.get("criado_em"),
            "atualizado_em": note.get("atualizado_em")
        })
    return jsonify(saida), 200


# POST - Criar anotação
@app.route("/notes", methods=["POST"])
def criar_note():
    dados = request.json
    if not dados or "titulo" not in dados or "conteudo" not in dados:
        return jsonify({"erro": "Campos 'titulo' e 'conteudo' são obrigatórios"}), 400

    agora = datetime.utcnow()
    note_id = mongo.db.notes.insert_one({
        "titulo": dados["titulo"],
        "conteudo": dados["conteudo"],
        "criado_em": agora,
        "atualizado_em": agora
    }).inserted_id

    return jsonify({
        "id": str(note_id),
        "titulo": dados["titulo"],
        "conteudo": dados["conteudo"],
        "criado_em": agora.isoformat(),
        "atualizado_em": agora.isoformat()
    }), 201


# PUT - Atualizar anotação
@app.route("/notes/<id>", methods=["PUT"])
def atualizar_note(id):
    dados = request.json
    agora = datetime.utcnow()
    atualizado = mongo.db.notes.find_one_and_update(
        {"_id": ObjectId(id)},
        {"$set": {
            "titulo": dados.get("titulo"),
            "conteudo": dados.get("conteudo"),
            "atualizado_em": agora
        }},
        return_document=True
    )
    if not atualizado:
        return jsonify({"erro": "Anotação não encontrada"}), 404
    return jsonify({
        "id": str(atualizado["_id"]),
        "titulo": atualizado["titulo"],
        "conteudo": atualizado["conteudo"],
        "criado_em": atualizado.get("criado_em"),
        "atualizado_em": atualizado.get("atualizado_em")
    }), 200


# DELETE - Remover anotação
@app.route("/notes/<id>", methods=["DELETE"])
def deletar_note(id):
    resultado = mongo.db.notes.delete_one({"_id": ObjectId(id)})
    if resultado.deleted_count == 0:
        return jsonify({"erro": "Anotação não encontrada"}), 404
    return jsonify({"mensagem": "Anotação deletada com sucesso"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)