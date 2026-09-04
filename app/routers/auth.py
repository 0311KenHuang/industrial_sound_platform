import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ..core.auth import current_user, hash_password, make_token, verify_password
from ..core.database import db
from ..schemas import LoginRequest, RegisterRequest


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
def register(request: RegisterRequest) -> Dict[str, Any]:
    from datetime import datetime

    now = datetime.now().isoformat(timespec="seconds")
    try:
        with db() as connection:
            cursor = connection.execute(
                "INSERT INTO users(username,email,password_hash,role,full_name,created_at) VALUES(?,?,?,?,?,?)",
                (request.username, request.email, hash_password(request.password), "operator", request.full_name, now),
            )
            user = {"id": cursor.lastrowid, "username": request.username, "email": request.email, "role": "operator", "full_name": request.full_name}
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "用户名或邮箱已存在") from exc
    return {"token": make_token(user), "user": user}


@router.post("/login")
def login(request: LoginRequest) -> Dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT * FROM users WHERE username=?", (request.username,)).fetchone()
    if not row or not verify_password(request.password, row["password_hash"]):
        raise HTTPException(401, "用户名或密码错误")
    user = dict(row)
    user.pop("password_hash", None)
    return {"token": make_token(user), "user": user}


@router.post("/logout")
def logout(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
    return {"ok": True}


@router.get("/me")
def me(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    return user
