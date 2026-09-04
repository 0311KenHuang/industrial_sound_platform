from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException

from .database import db


JWT_SECRET = os.getenv("SOUNDNET_JWT_SECRET") or secrets.token_urlsafe(32)


def hash_password(password: str) -> str:
    try:
        import bcrypt
        return "bcrypt$" + bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    except Exception:
        salt = secrets.token_bytes(16)
        return "pbkdf2$" + base64.urlsafe_b64encode(salt).decode() + "$" + hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 180000).hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        if encoded.startswith("bcrypt$"):
            import bcrypt
            return bcrypt.checkpw(password.encode(), encoded[7:].encode())
        _, salt_text, digest = encoded.split("$", 2)
        salt = base64.urlsafe_b64decode(salt_text.encode())
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 180000).hex(), digest)
    except Exception:
        return False


def make_token(user: Dict[str, Any]) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"sub": user["id"], "username": user["username"], "role": user["role"], "exp": int((datetime.now() + timedelta(hours=12)).timestamp())}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "需要登录后访问")
    try:
        header, payload, signature = authorization[7:].split(".")
        expected = hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        token_header = json.loads(base64.urlsafe_b64decode(header + "=" * (-len(header) % 4)))
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if token_header.get("alg") != "HS256" or token_header.get("typ") != "JWT":
            raise ValueError
        if not claims.get("sub") or not isinstance(claims.get("exp"), (int, float)):
            raise ValueError
        if not hmac.compare_digest(expected, supplied) or claims["exp"] < int(datetime.now().timestamp()):
            raise ValueError
    except Exception as exc:
        raise HTTPException(401, "登录凭证无效或已过期") from exc
    with db() as connection:
        row = connection.execute("SELECT id,username,email,role,full_name,is_active FROM users WHERE id=? AND is_active=1", (claims["sub"],)).fetchone()
    if not row:
        raise HTTPException(401, "用户不存在或已停用")
    return dict(row)
