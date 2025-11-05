# app.py (reports service - matching tasks service structure)
import os
import time
import logging
from functools import wraps
from datetime import datetime
import json

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument
from jose import jwt
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask_cors import CORS

# Load env
load_dotenv()

# Logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("reports-app")

app = Flask(__name__)

# -------------------------
# App config
# -------------------------
app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/reportsdb")
TASKS_SERVICE_URL = os.getenv("TASKS_SERVICE_URL", "http://tasks-service:5000")  # usado para fallback sync validation

# FRONTEND_ORIGINS: comma separated list OR "*" (like tasks service)
FRONTEND_ORIGINS = os.getenv("FRONTEND_ORIGINS", "http://localhost:5173")
if FRONTEND_ORIGINS.strip() == "*":
    cors_origins = "*"
else:
    cors_origins = [o.strip() for o in FRONTEND_ORIGINS.split(",") if o.strip()]

# Initialize CORS with full configuration
CORS(app,
     resources={r"/*": {"origins": cors_origins}},
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization", "Accept"],
     expose_headers=["Content-Type"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

# -------------------------
# Auth0 / JWKS config
# -------------------------
AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN") or os.getenv("VITE_AUTH0_DOMAIN")
AUTH0_AUDIENCE = os.getenv("API_AUDIENCE") or os.getenv("AUTH0_AUDIENCE") or os.getenv("VITE_AUTH0_AUDIENCE")
ALGORITHMS = ["RS256"]

# JWKS cache
_JWKS_CACHE = {"fetched_at": 0, "jwks": None, "ttl": 3600}


def _get_jwks():
    if not AUTH0_DOMAIN:
        raise RuntimeError("AUTH0_DOMAIN não configurado (ver .env)")
    now = time.time()
    if _JWKS_CACHE["jwks"] and now - _JWKS_CACHE["fetched_at"] < _JWKS_CACHE["ttl"]:
        return _JWKS_CACHE["jwks"]
    jwks_url = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"
    r = requests.get(jwks_url, timeout=5)
    r.raise_for_status()
    jwks = r.json()
    _JWKS_CACHE.update({"jwks": jwks, "fetched_at": now})
    return jwks


# -------------------------
# Helpers / Auth decorator
# -------------------------
def requires_auth_api(required_scope: str = None):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if app.config.get("TESTING"):
                request.current_user = {"sub": "test-user"}
                return f(*args, **kwargs)

            auth = request.headers.get("Authorization", None)
            if not auth:
                return jsonify({"error": "Authorization header missing"}), 401

            parts = auth.split()
            if parts[0].lower() != "bearer" or len(parts) != 2:
                return jsonify({"error": "Invalid Authorization header"}), 401
            token = parts[1]

            try:
                unverified_header = jwt.get_unverified_header(token)
            except Exception:
                return jsonify({"error": "Invalid token header"}), 401

            try:
                jwks = _get_jwks()
            except Exception as e:
                logger.exception("Failed to fetch JWKS")
                return jsonify({"error": f"Erro ao buscar JWKS: {str(e)}"}), 500

            rsa_key = {}
            for key in jwks.get("keys", []):
                if key.get("kid") == unverified_header.get("kid"):
                    rsa_key = {
                        "kty": key.get("kty"),
                        "kid": key.get("kid"),
                        "use": key.get("use"),
                        "n": key.get("n"),
                        "e": key.get("e")
                    }
                    break

            if not rsa_key:
                return jsonify({"error": "Appropriate JWK not found"}), 401

            try:
                payload = jwt.decode(
                    token,
                    rsa_key,
                    algorithms=ALGORITHMS,
                    audience=AUTH0_AUDIENCE,
                    issuer=f"https://{AUTH0_DOMAIN}/"
                )
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "Token expired"}), 401
            except Exception as e:
                logger.warning("Token validation error: %s", e)
                return jsonify({"error": f"Token inválido: {str(e)}"}), 401

            if required_scope:
                scopes = payload.get("scope", "")
                scopes_list = scopes.split() if isinstance(scopes, str) else []
                if required_scope not in scopes_list:
                    return jsonify({"error": "Insufficient scope"}), 403

            request.current_user = payload
            return f(*args, **kwargs)
        return decorated
    return decorator


# -------------------------
# DB
# -------------------------
mongo = PyMongo(app)

# -------------------------
# HTTP session com retries (para fallback sync validation)
# -------------------------
def make_http_session():
    session = requests.Session()
    retries = Retry(total=1, backoff_factor=0.2, status_forcelist=[500,502,503,504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

_http_session = make_http_session()


# -------------------------
# Logging
# -------------------------
@app.before_request
def log_request_info():
    logger.debug("Incoming request: %s %s", request.method, request.path)
    # show only key headers and NEVER Authorization
    hdrs = {k: v for k, v in request.headers.items() if k in ("Host", "Origin", "Content-Type")}
    logger.debug("Headers: %s", hdrs)
    try:
        logger.debug("Body preview: %s", request.get_data(as_text=True)[:1000])
    except Exception:
        pass


# -------------------------
# Helpers: validation híbrida de task_id
# -------------------------
def validate_task_id_hybrid(task_id):
    # 1) tentar no snapshot local
    try:
        obj_id = ObjectId(task_id)
    except Exception:
        return False, "invalid_id", None

    snap = mongo.db.task_snapshots.find_one({"_id": obj_id})
    if snap:
        return True, "ok", snap

    # 2) fallback sync para tasks-service
    try:
        r = _http_session.get(f"{TASKS_SERVICE_URL}/tarefas/{task_id}", timeout=0.8)
        if r.status_code == 200:
            task = r.json()
            # salvar snapshot local (usando _id como ObjectId)
            try:
                task_doc = {
                    "_id": ObjectId(task_id),
                    "titulo": task.get("titulo"),
                    "descricao": task.get("descricao"),
                    "owner": task.get("owner") if isinstance(task, dict) else None,
                    "status": "open",
                    "criado_em": task.get("criado_em", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                    "atualizado_em": task.get("atualizado_em", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                }
                mongo.db.task_snapshots.replace_one({"_id": ObjectId(task_id)}, task_doc, upsert=True)
            except Exception as e:
                logger.warning("Falha ao persistir snapshot vindo do tasks-service: %s", e)
            return True, "ok", task
        elif r.status_code == 404:
            return False, "not_found", None
        else:
            return None, "unavailable", None
    except requests.RequestException as e:
        logger.warning("Fallback sync para tasks-service falhou: %s", e)
        return None, "unavailable", None


# -------------------------
# Helpers: idempotency util
# -------------------------
def get_idempotency_record(collection_name, idempotency_key):
    if not idempotency_key:
        return None
    return mongo.db.idempotency.find_one({"collection": collection_name, "idempotency_key": idempotency_key})

def save_idempotency_record(collection_name, idempotency_key, resource):
    if not idempotency_key:
        return
    mongo.db.idempotency.replace_one(
        {"collection": collection_name, "idempotency_key": idempotency_key},
        {"collection": collection_name, "idempotency_key": idempotency_key, "resource": resource},
        upsert=True
    )


# -------------------------
# Routes
# -------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "reports"}), 200

@app.route("/ready", methods=["GET"])
def ready():
    try:
        mongo.db.command("ping")
        return jsonify({"ready": True}), 200
    except Exception:
        return jsonify({"ready": False}), 503


@app.route("/reports", methods=["GET"])
@requires_auth_api()
def listar_reports():
    reports = mongo.db.reports.find()
    out = []
    for report in reports:
        out.append({
            "id": str(report["_id"]),
            "titulo": report.get("titulo"),
            "conteudo": report.get("conteudo"),
            "task_id": str(report.get("task_id")) if report.get("task_id") else None,
            "criado_em": report.get("criado_em").isoformat() if report.get("criado_em") else None,
            "atualizado_em": report.get("atualizado_em").isoformat() if report.get("atualizado_em") else None
        })
    return jsonify(out), 200


@app.route("/reports", methods=["POST"])
@requires_auth_api()
def criar_report():
    dados = request.json
    if not dados or "titulo" not in dados or "conteudo" not in dados or "task_id" not in dados:
        return jsonify({"error": "Campos 'titulo', 'conteudo' e 'task_id' são obrigatórios"}), 400

    task_id = dados["task_id"]

    # idempotency
    idempotency_key = request.headers.get("Idempotency-Key")
    existing = get_idempotency_record("reports", idempotency_key)
    if existing:
        return jsonify(existing["resource"]), 200

    valid, reason, snapshot = validate_task_id_hybrid(task_id)
    if valid is True:
        agora = datetime.utcnow()
        report_doc = {
            "titulo": dados["titulo"],
            "conteudo": dados["conteudo"],
            "task_id": ObjectId(task_id),
            "criado_em": agora,
            "atualizado_em": agora,
            "status": "pending"
        }
        report_id = mongo.db.reports.insert_one(report_doc).inserted_id

        resource = {
            "id": str(report_id),
            "titulo": report_doc["titulo"],
            "conteudo": report_doc["conteudo"],
            "task_id": str(report_doc["task_id"]),
            "criado_em": agora.isoformat(),
            "atualizado_em": agora.isoformat()
        }

        # salvar idempotency
        save_idempotency_record("reports", idempotency_key, resource)

        return jsonify(resource), 201
    elif valid is False:
        if reason == "invalid_id":
            return jsonify({"error": "task_id inválido"}), 400
        return jsonify({"error": "Task não encontrada"}), 400
    else:
        # unavailable -> erro operacional (tasks-service inacessível)
        return jsonify({"error": "Não foi possível validar a task no momento. Tente novamente mais tarde."}), 503


@app.route("/reports/<id>", methods=["PUT"])
@requires_auth_api()
def atualizar_report(id):
    dados = request.json or {}
    try:
        obj_id = ObjectId(id)
    except Exception:
        return jsonify({"error": "ID inválido"}), 400

    agora = datetime.utcnow()
    update_fields = {"atualizado_em": agora}
    if "titulo" in dados:
        update_fields["titulo"] = dados["titulo"]
    if "conteudo" in dados:
        update_fields["conteudo"] = dados["conteudo"]

    atualizado = mongo.db.reports.find_one_and_update(
        {"_id": obj_id},
        {"$set": update_fields},
        return_document=ReturnDocument.AFTER
    )
    if not atualizado:
        return jsonify({"error": "Relatório não encontrado"}), 404

    return jsonify({
        "id": str(atualizado["_id"]),
        "titulo": atualizado.get("titulo"),
        "conteudo": atualizado.get("conteudo"),
        "task_id": str(atualizado.get("task_id")) if atualizado.get("task_id") else None,
        "criado_em": atualizado.get("criado_em").isoformat() if atualizado.get("criado_em") else None,
        "atualizado_em": atualizado.get("atualizado_em").isoformat() if atualizado.get("atualizado_em") else None
    }), 200


@app.route("/reports/<id>", methods=["DELETE"])
@requires_auth_api()
def deletar_report(id):
    try:
        obj_id = ObjectId(id)
    except Exception:
        return jsonify({"error": "ID inválido"}), 400

    resultado = mongo.db.reports.delete_one({"_id": obj_id})
    if resultado.deleted_count == 0:
        return jsonify({"error": "Relatório não encontrado"}), 404
    return jsonify({"message": "Relatório deletado com sucesso"}), 200


# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    # índices
    try:
        mongo.db.reports.create_index("task_id")
        mongo.db.task_snapshots.create_index([("_id", 1)])
        mongo.db.idempotency.create_index([("collection", 1), ("idempotency_key", 1)], unique=True, sparse=True)
    except Exception:
        logger.warning("Falha ao criar índices iniciais")

    port = int(os.getenv("PORT", os.getenv("FLASK_RUN_PORT", 5001)))
    debug_flag = (os.getenv("FLASK_DEBUG", "false").lower() == "true")
    app.run(host="0.0.0.0", port=port, debug=debug_flag)
