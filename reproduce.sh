#!/usr/bin/env bash
# Reproduz, sem Ollama, as tabelas/ICs/figura do artigo a partir das saídas congeladas.
set -e
cd "$(dirname "$0")"
python -m pip install -r requirements.txt
python metricas_utilidade.py
python analise_estatistica.py
python figura_tradeoff.py
echo "OK: veja results/ e fig_tradeoff.pdf"
