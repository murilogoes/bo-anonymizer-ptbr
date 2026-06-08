# -*- coding: utf-8 -*-
"""Barras horizontais: recall de seguranca (IC 95%) por configuracao,
com retencao de conteudo anotada (utilidade). Le resultados congelados."""
import csv, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
def load(p):
    d={}
    with open(os.path.join(BASE,p),newline="") as f:
        for r in csv.DictReader(f): d[r["config"]]=r
    return d
util=load("metricas_utilidade.csv"); ic=load("bootstrap_ic.csv")

ordem=[
 ("regex_only","regex (baseline)",False),
 ("ner_bertimbau","BERTimbau-LeNER",False),
 ("llm_qwen3-8b","qwen3:8b (recommended)",True),
 ("ner_spacy","spaCy / Presidio",False),
 ("llm_gemma3-12b","gemma3:12b",False),
 ("llm_llama3.1-8b","llama3.1:8b",False),
 ("encadeado_qwen3-8b_ner_llm","chained ner$\\rightarrow$llm",False),
 ("encadeado_qwen3-8b_llm_ner","chained llm$\\rightarrow$ner",False),
 ("hibrido_qwen3-8b","union spaCy$\\cup$qwen3 (highest recall)",True),
]
ys=list(range(len(ordem)))
fig,ax=plt.subplots(figsize=(6.4,3.9))
for y,(k,lab,hi_) in zip(ys,ordem):
    seg=float(ic[k]["seg_recall_ponto"])
    lo=float(ic[k]["seg_recall_ic95_inf"]); hp=float(ic[k]["seg_recall_ic95_sup"])
    ret=float(util[k]["retencao_conteudo"])*100
    col="#b22222" if hi_ else "#5a6b7b"
    ax.barh(y, seg, color=col, alpha=0.92 if hi_ else 0.82, height=0.62, zorder=2)
    ax.errorbar(seg, y, xerr=[[seg-lo],[hp-seg]], fmt="none",
                ecolor="#222222", elinewidth=1, capsize=2.5, zorder=3)
    ax.text(hp+0.006, y, ("ret. %.1f%%"%ret), va="center", ha="left",
            fontsize=7, color="#333333")

ax.set_yticks(ys)
ax.set_yticklabels([l for _,l,_ in ordem], fontsize=7.6)
for t,(_,_,hi_) in zip(ax.get_yticklabels(),ordem):
    if hi_: t.set_color("#b22222"); t.set_fontweight("bold")
ax.set_xlabel(u"Safety recall (bars, 95% bootstrap CI) — content retention annotated on the right", fontsize=7.8)
ax.set_xlim(0.60,1.07)
ax.set_ylim(-0.7,len(ordem)-0.3)
ax.axvline(1.0, color="#bbbbbb", ls="--", lw=0.7, zorder=1)
ax.tick_params(axis="x", labelsize=8)
for s in ["top","right"]: ax.spines[s].set_visible(False)
fig.tight_layout()
out=os.path.join(os.path.dirname(os.path.abspath(__file__)),"fig_tradeoff.pdf")
fig.savefig(out,bbox_inches="tight"); print("salvo:",out)
