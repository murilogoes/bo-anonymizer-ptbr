# -*- coding: utf-8 -*-
"""Core do aplicativo de anonimização (reaproveita a pipeline do artigo).

Presets (mapeiam os achados do artigo):
  - "Recomendado (qwen3:8b)"   : melhor equilíbrio segurança/utilidade (requer Ollama).
  - "Máxima segurança (união)" : spaCy ∪ qwen3, maior não-vazamento (requer Ollama + spaCy).
  - "Leve/offline (spaCy)"     : sem LLM; roda em qualquer máquina (requer apenas spaCy).

Tudo executa 100% localmente. Nenhum dado sai da máquina.
"""
import os
import sys
import yaml

# app/ é autocontida: os módulos da pipeline e o config.yaml ficam nesta mesma pasta.
_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from estagio1_regex import aplicar_estagio1
from estagio2_motores import criar_motor, aplicar_substituicoes

PRESETS = {
    "Recomendado (qwen3:8b)":   {"motor": "llm",     "modelo": "qwen3:8b",
                                 "requer_ollama": True,  "requer_spacy": False},
    "Máxima segurança (união)": {"motor": "hibrido", "modelo": "qwen3:8b", "ner_backend": "spacy",
                                 "requer_ollama": True,  "requer_spacy": True},
    "Leve/offline (spaCy)":     {"motor": "ner",     "ner_backend": "spacy",
                                 "requer_ollama": False, "requer_spacy": True},
}

def carregar_config(path=None):
    path = path or os.path.join(_BASE, "config.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

_CACHE = {}
def carregar_motor(preset, cfg=None):
    """Instancia (uma vez) o motor do Estágio 2 para o preset."""
    if preset not in PRESETS:
        raise ValueError(f"preset desconhecido: {preset}")
    cfg = cfg or carregar_config()
    if preset not in _CACHE:
        p = PRESETS[preset]
        _CACHE[preset] = criar_motor(cfg, motor=p["motor"],
                                     modelo=p.get("modelo"),
                                     ner_backend=p.get("ner_backend", "spacy"))
    return _CACHE[preset]

def anonimizar_texto(texto, preset, cfg=None):
    """Anonimiza um único texto. Retorna o texto anonimizado."""
    cfg = cfg or carregar_config()
    motor = carregar_motor(preset, cfg)
    txt1, _caps = aplicar_estagio1(str(texto), retornar_capturas=True)
    ent = motor.extrair(txt1)
    txt2, _n = aplicar_substituicoes(txt1, ent, numerar=True)
    return txt2

def anonimizar_serie(valores, preset, cfg=None, progresso=None):
    """Anonimiza uma lista/série de textos. `progresso(frac)` é opcional (0..1)."""
    cfg = cfg or carregar_config()
    motor = carregar_motor(preset, cfg)
    out = []
    n = max(1, len(valores))
    for i, val in enumerate(valores):
        txt1, _ = aplicar_estagio1(str(val) if val is not None else "", retornar_capturas=True)
        ent = motor.extrair(txt1)
        txt2, _ = aplicar_substituicoes(txt1, ent, numerar=True)
        out.append(txt2)
        if progresso:
            progresso((i + 1) / n)
    return out

def checar_ambiente(cfg=None):
    """Verifica se Ollama está acessível e se o modelo spaCy está instalado."""
    cfg = cfg or carregar_config()
    status = {"ollama": False, "spacy": False, "spacy_model": cfg["ner"]["spacy_model"]}
    try:
        import requests
        url = f"http://{cfg['llm']['host']}:{cfg['llm']['porta']}/api/tags"
        status["ollama"] = requests.get(url, timeout=2).ok
    except Exception:
        status["ollama"] = False
    try:
        import spacy
        status["spacy"] = spacy.util.is_package(cfg["ner"]["spacy_model"])
    except Exception:
        status["spacy"] = False
    return status

def presets_disponiveis(status):
    """Lista de presets utilizáveis dado o ambiente; sempre devolve ao menos um."""
    disp = []
    for nome, p in PRESETS.items():
        ok = (not p["requer_ollama"] or status.get("ollama")) and \
             (not p["requer_spacy"] or status.get("spacy"))
        disp.append((nome, ok))
    return disp
