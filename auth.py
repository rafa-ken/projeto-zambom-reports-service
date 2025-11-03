# auth.py
import os
import time
import requests
from functools import wraps
from flask import request, jsonify, _request_ctx_stack
from jose import jwt, jwk
from jose.utils import base64url_decode

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")            # ex: dev-abc123.auth0.com
API_AUDIENCE = os.getenv("API_AUDIENCE")            # ex: https://api.example.local
JWKS_URL = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"
ALGORITHMS = ["RS256"]

# Simple in-memory cache for JWKS
_cached_jwks = None
_cached_jwks_ts = 0
JWKS_CACHE_TTL = 60 * 60  # 1 hour

def get_jwks():
    global _cached_jwks, _cached_jwks_ts
    if _cached_jwks and (time.time() - _cached_jwks_ts) < JWKS_CACHE_TTL:
        return _cached_jwks
    r = requests.get(JWKS_URL, timeout=5)
    r.raise_for_status()
    _cached_jwks = r.json()
    _cached_jwks_ts = time.time()
    return _cached_jwks

class AuthError(Exception):
    def __init__(self, err, status_code):
        self.error = err
        self.status_code = status_code

def _get_token_auth_header():
    auth = request.headers.get("Authorization", None)
    if not auth:
        raise AuthError({"code":"authorization_header_missing",
                         "description":"Authorization header is expected"}, 401)
    parts = auth.split()
    if parts[0].lower() != "bearer":
        raise AuthError({"code":"invalid_header","description":"Authorization header must start with Bearer"}, 401)
    elif len(parts) == 1:
        raise AuthError({"code":"invalid_header","description":"Token not found"}, 401)
    elif len(parts) > 2:
        raise AuthError({"code":"invalid_header","description":"Authorization header must be Bearer token"}, 401)
    token = parts[1]
    return token

def requires_auth(required_scope=None):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            token = _get_token_auth_header()
            jwks = get_jwks()
            try:
                unverified_header = jwt.get_unverified_header(token)
            except Exception:
                raise AuthError({"code":"invalid_header","description":"Invalid header"}, 401)

            rsa_key = {}
            for key in jwks["keys"]:
                if key["kid"] == unverified_header.get("kid"):
                    rsa_key = {
                        "kty": key["kty"],
                        "kid": key["kid"],
                        "use": key["use"],
                        "n": key["n"],
                        "e": key["e"]
                    }
            if not rsa_key:
                raise AuthError({"code":"invalid_header","description":"Unable to find appropriate key"}, 401)

            try:
                payload = jwt.decode(
                    token,
                    rsa_key,
                    algorithms=ALGORITHMS,
                    audience=API_AUDIENCE,
                    issuer=f"https://{AUTH0_DOMAIN}/"
                )
            except jwt.ExpiredSignatureError:
                raise AuthError({"code":"token_expired","description":"token is expired"}, 401)
            except jwt.JWTClaimsError:
                raise AuthError({"code":"invalid_claims","description":"incorrect claims, please check the audience and issuer"}, 401)
            except Exception:
                raise AuthError({"code":"invalid_header","description":"Unable to parse authentication token."}, 401)

            # Optional scope check (if using scopes)
            if required_scope:
                token_scopes = payload.get("scope", "")
                if required_scope not in token_scopes.split():
                    raise AuthError({"code":"insufficient_scope","description":"You don't have access to this resource"}, 403)

            # attach user info to flask global context
            _request_ctx_stack.top.current_user = payload
            return f(*args, **kwargs)
        return wrapper
    return decorator

# error handler helper
def register_auth_error_handlers(app):
    @app.errorhandler(AuthError)
    def handle_auth_error(ex):
        return jsonify(ex.error), ex.status_code
