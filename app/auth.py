# -*- coding: utf-8 -*-
"""Autenticação e gestão de usuários/chaves de API em SQLite local.

Sem SGBD externo: um único arquivo `anonimizador.db` nesta pasta.
Senhas: PBKDF2-HMAC-SHA256 (stdlib) com salt por usuário.
Chaves de API: token aleatório; armazena-se apenas o hash (SHA-256).
"""
import os
import sqlite3
import hashlib
import secrets
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anonimizador.db")
PBKDF2_ITER = 200_000
ROLES = ("comum", "admin")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            pw_hash  TEXT NOT NULL,
            salt     TEXT NOT NULL,
            role     TEXT NOT NULL DEFAULT 'comum',
            created_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS api_keys(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label    TEXT,
            key_hash TEXT UNIQUE NOT NULL,
            owner    TEXT,
            created_at TEXT NOT NULL,
            active   INTEGER NOT NULL DEFAULT 1)""")


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _hash_pw(senha, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"),
                               bytes.fromhex(salt_hex), PBKDF2_ITER).hex()


# ----------------------------------------------------------------- usuários
def contar_usuarios():
    with _conn() as c:
        return c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]


def criar_usuario(username, senha, role="comum"):
    username = (username or "").strip()
    if not username or not senha:
        raise ValueError("Usuário e senha são obrigatórios.")
    if role not in ROLES:
        raise ValueError("Perfil inválido.")
    salt = secrets.token_hex(16)
    init_db()
    try:
        with _conn() as c:
            c.execute("INSERT INTO users(username,pw_hash,salt,role,created_at) "
                      "VALUES(?,?,?,?,?)",
                      (username, _hash_pw(senha, salt), salt, role, _now()))
    except sqlite3.IntegrityError:
        raise ValueError("Já existe um usuário com esse nome.")


def verificar_login(username, senha):
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE username=?",
                      ((username or "").strip(),)).fetchone()
    if not r:
        return None
    if secrets.compare_digest(_hash_pw(senha, r["salt"]), r["pw_hash"]):
        return {"username": r["username"], "role": r["role"]}
    return None


def listar_usuarios():
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT username, role, created_at FROM users ORDER BY username")]


def alterar_senha(username, nova_senha):
    if not nova_senha:
        raise ValueError("Senha vazia.")
    salt = secrets.token_hex(16)
    with _conn() as c:
        cur = c.execute("UPDATE users SET pw_hash=?, salt=? WHERE username=?",
                        (_hash_pw(nova_senha, salt), salt, username))
        if cur.rowcount == 0:
            raise ValueError("Usuário não encontrado.")


def alterar_papel(username, role):
    if role not in ROLES:
        raise ValueError("Perfil inválido.")
    with _conn() as c:
        c.execute("UPDATE users SET role=? WHERE username=?", (role, username))


def remover_usuario(username):
    with _conn() as c:
        # impede remover o último admin
        admins = c.execute("SELECT COUNT(*) n FROM users WHERE role='admin'").fetchone()["n"]
        r = c.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
        if r and r["role"] == "admin" and admins <= 1:
            raise ValueError("Não é possível remover o último administrador.")
        c.execute("DELETE FROM users WHERE username=?", (username,))


# ----------------------------------------------------------------- chaves de API
def gerar_api_key(label, owner):
    raw = secrets.token_urlsafe(32)
    kh = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    init_db()
    with _conn() as c:
        c.execute("INSERT INTO api_keys(label,key_hash,owner,created_at,active) "
                  "VALUES(?,?,?,?,1)", (label or "", kh, owner or "", _now()))
    return raw  # exibido UMA vez; não é recuperável depois


def validar_api_key(raw):
    if not raw:
        return False
    kh = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    with _conn() as c:
        r = c.execute("SELECT active FROM api_keys WHERE key_hash=?", (kh,)).fetchone()
    return bool(r and r["active"] == 1)


def listar_api_keys():
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, label, owner, created_at, active FROM api_keys ORDER BY id DESC")]


def revogar_api_key(key_id):
    with _conn() as c:
        c.execute("UPDATE api_keys SET active=0 WHERE id=?", (key_id,))
