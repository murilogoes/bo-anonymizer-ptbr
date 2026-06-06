# -*- coding: utf-8 -*-
"""API REST local de anonimização (FastAPI), autenticada por chave (Bearer token).

Rodar:  uvicorn api:app --host 127.0.0.1 --port 8000
Exemplo:
  curl -X POST http://127.0.0.1:8000/anonimizar \
       -H "Authorization: Bearer SUA_CHAVE" \
       -H "Content-Type: application/json" \
       -d '{"texto":"Vítima João da Silva, tel (11) 98765-4321."}'

Por padrão escuta apenas em 127.0.0.1 (somente local). Para expor na rede interna,
use atrás de um proxy com HTTPS e restrinja por firewall.
"""
from typing import Optional
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

import anonimizador_core as core
import auth

auth.init_db()
app = FastAPI(title="Anonimizador de BO — API", version="1.0")

PRESET_PADRAO = "Recomendado (qwen3:8b)"


class ReqAnon(BaseModel):
    texto: str
    preset: Optional[str] = PRESET_PADRAO


def _exigir_chave(authorization: Optional[str]):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401,
                            detail="Envie 'Authorization: Bearer <chave>'.")
    token = authorization.split(" ", 1)[1].strip()
    if not auth.validar_api_key(token):
        raise HTTPException(status_code=401, detail="Chave de API inválida ou revogada.")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/anonimizar")
def anonimizar(req: ReqAnon, authorization: Optional[str] = Header(default=None)):
    _exigir_chave(authorization)
    preset = req.preset or PRESET_PADRAO
    if preset not in core.PRESETS:
        raise HTTPException(status_code=400,
                            detail=f"preset inválido. Opções: {list(core.PRESETS)}")
    try:
        return {"preset": preset, "anonimizado": core.anonimizar_texto(req.texto, preset)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao anonimizar: {e}")
