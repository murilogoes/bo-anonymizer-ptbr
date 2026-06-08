# -*- coding: utf-8 -*-
"""Mede a variância run-to-run do qwen3:8b (não-determinismo do LLM).

Roda o qwen3:8b TRÊS vezes do zero (checkpoint limpo a cada rodada), avalia cada
execução e reporta média ± desvio do recall de segurança (macro). Tudo isolado em
`variancia_qwen3/` — NÃO sobrescreve os resultados publicados.

Pré-requisitos: Ollama rodando + `ollama pull qwen3:8b`; `config.yaml` apontando para
um dataset com gabarito (as colunas de anotação). Rode na pasta do projeto:
    python variancia_qwen3.py
Tempo estimado: ~1h por rodada (3,7 s/BO x 996) -> ~3h no total.
"""
import os, sys, csv, shutil, subprocess, statistics, yaml

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "variancia_qwen3")
os.makedirs(WORK, exist_ok=True)

# config isolado (não toca saidas/ nem results/ publicados)
cfg = yaml.safe_load(open(os.path.join(BASE, "config.yaml"), encoding="utf-8"))
cfg["paths"]["saida_dir"] = os.path.join("variancia_qwen3", "saidas")
cfg["paths"]["checkpoint_dir"] = os.path.join("variancia_qwen3", "ckpt")
cfg["paths"]["resultados_dir"] = os.path.join("variancia_qwen3", "resultados")
for d in ("saidas", "ckpt", "resultados"):
    os.makedirs(os.path.join(WORK, d), exist_ok=True)
cfg_path = os.path.join(BASE, "config_variancia.yaml")
yaml.safe_dump(cfg, open(cfg_path, "w", encoding="utf-8"), allow_unicode=True)

TAG = "llm_qwen3-8b"
vals = []
for i in (1, 2, 3):
    ck = os.path.join(WORK, "ckpt", TAG)
    if os.path.isdir(ck):
        shutil.rmtree(ck)                       # rodada do ZERO (não retoma)
    out = os.path.join(WORK, "saidas", f"{TAG}.csv")
    if os.path.exists(out):
        os.remove(out)
    print(f"\n===== RODADA {i}/3: gerando (qwen3:8b) — pode levar ~1h =====")
    subprocess.run([sys.executable, "pipeline_anonimizacao_roubo.py",
                    "--motor", "llm", "--modelo", "qwen3:8b",
                    "--config", "config_variancia.yaml"], check=True, cwd=BASE)
    run_out = os.path.join(WORK, "saidas", f"{TAG}_run{i}.csv")
    shutil.copy(out, run_out)
    print(f"===== RODADA {i}/3: avaliando =====")
    subprocess.run([sys.executable, "avaliar_pipeline.py",
                    "--saida", run_out, "--config", "config_variancia.yaml"],
                   check=True, cwd=BASE)
    tab = os.path.join(WORK, "resultados", "tabela_comparativa.csv")
    rows = [r for r in csv.DictReader(open(tab, encoding="utf-8"))
            if r["config"] == f"{TAG}_run{i}"]
    v = float(rows[-1]["recall_seguranca_macro"])
    vals.append(v)
    print(f"   -> rodada {i}: recall de segurança (macro) = {v:.4f}")

m = statistics.mean(vals)
sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
print("\n==================== RESULTADO ====================")
print("valores das 3 rodadas:", [f"{v:.4f}" for v in vals])
print(f"média = {m:.4f}   desvio-padrão (amostral) = {sd:.4f}")
print("\nFrase pronta para o artigo (cole no Claude):")
print(f"  qwen3:8b — 3 execuções: safety recall macro = {m:.3f} ± {sd:.3f} "
      f"(valores {', '.join(f'{v:.3f}' for v in vals)})")
