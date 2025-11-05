# app.py (reports service - matching tasks service structure)
import os
import time
import logging
from functools import wraps
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from pymongo import ReturnDocument
from jose import jwt
import requests
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
# Support either API_AUDIENCE or AUTH0_AUDIENCE env names for convenience
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
    """
    Decorator to require a Bearer access token (Auth0).
    If required_scope is provided, also checks that scope exists in token.
    Bypasses authentication when app.config['TESTING'] is True.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # Bypass authentication in test mode
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

            # scope check (optional)
            if required_scope:
                scopes = payload.get("scope", "")
                scopes_list = scopes.split() if isinstance(scopes, str) else []
                if required_scope not in scopes_list:
                    return jsonify({"error": "Insufficient scope"}), 403

            # attach claims
            request.current_user = payload
            return f(*args, **kwargs)
        return decorated
    return decorator


# -------------------------
# DB
# -------------------------
mongo = PyMongo(app)


# -------------------------
# Logging
# -------------------------
@app.before_request
def log_request_info():
    logger.debug("Incoming request: %s %s", request.method, request.path)
    # show only key headers to avoid leaking secrets in logs
    hdrs = {k: v for k, v in request.headers.items() if k in ("Host", "Origin", "Authorization", "Content-Type")}
    logger.debug("Headers: %s", hdrs)
    try:
        logger.debug("Body preview: %s", request.get_data(as_text=True)[:1000])
    except Exception:
        pass


# -------------------------
# Routes
# -------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "reports"}), 200


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
            "criado_em": report.get("criado_em").isoformat() if report.get("criado_em") else None,
            "atualizado_em": report.get("atualizado_em").isoformat() if report.get("atualizado_em") else None
        })
    return jsonify(out), 200


@app.route("/reports", methods=["POST"])
@requires_auth_api()
def criar_report():
    dados = request.json
    if not dados or "titulo" not in dados or "conteudo" not in dados:
        return jsonify({"error": "Campos 'titulo' e 'conteudo' são obrigatórios"}), 400

    agora = datetime.utcnow()
    report_doc = {
        "titulo": dados["titulo"],
        "conteudo": dados["conteudo"],
        "criado_em": agora,
        "atualizado_em": agora
    }
    report_id = mongo.db.reports.insert_one(report_doc).inserted_id

    return jsonify({
        "id": str(report_id),
        "titulo": report_doc["titulo"],
        "conteudo": report_doc["conteudo"],
        "criado_em": agora.isoformat(),
        "atualizado_em": agora.isoformat()
    }), 201


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
    port = int(os.getenv("PORT", os.getenv("FLASK_RUN_PORT", 5001)))
    debug_flag = (os.getenv("FLASK_DEBUG", "false").lower() == "true")
    app.run(host="0.0.0.0", port=port, debug=debug_flag)
