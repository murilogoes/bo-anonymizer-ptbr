"""
metricas_utilidade.py — Métricas de UTILIDADE por configuração (sem reexecutar modelos)
=======================================================================================
A partir de saidas/*.csv (resultados por registro congelados), calcula por configuração:

  1. taxa_sobre_remocao  = FP / (TP + FP)          (fração do que foi removido que não
                                                    era PII daquele tipo no gabarito)
  2. pct_texto_substituido = fração de CARACTERES do texto original substituídos
                             por placeholders (1 - retencao)
  3. retencao_conteudo   = fração de caracteres da narrativa preservados no texto
                           anonimizado (excluídos os placeholders)

Reconciliação: TP/FP recomputados são comparados com resultados_avaliacao/
<config>_por_tipo.csv; divergências são reportadas.

Saída: resultados_avaliacao/metricas_utilidade.csv
Uso:   python metricas_utilidade.py
"""
import csv
import glob
import os
import re

from eval_comum import (carregar_cfg, carregar_gabarito, construir_de_para,
                        stats_por_registro, agregar)

RE_PLACEHOLDER = re.compile(r'\[[A-ZÀ-Ü_]+(?:_\d+)?\]')


def utilidade_texto(regs):
    """% de caracteres substituídos e retenção, mediados sobre os registros."""
    pcts, rets = [], []
    for reg in regs:
        orig = reg['texto_entrada'] or ''
        anon = reg['texto_anonimizado'] or ''
        if not orig:
            continue
        mantido = len(RE_PLACEHOLDER.sub('', anon))
        ret = min(1.0, mantido / len(orig))
        rets.append(ret)
        pcts.append(1.0 - ret)
    n = max(1, len(rets))
    return sum(pcts) / n, sum(rets) / n


def reconciliar(tag, agg, res_dir):
    """Compara TP/FN/FP agregados com o *_por_tipo.csv congelado."""
    path = os.path.join(res_dir, f'{tag}_por_tipo.csv')
    if not os.path.exists(path):
        return 'sem_arquivo'
    ok = True
    with open(path, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            c = row['tipo']
            if (agg['tp'][c] != int(row['tp']) or agg['fn'][c] != int(row['fn'])
                    or agg['fp'][c] != int(row['fp'])):
                print(f'  [DIVERGÊNCIA] {tag}/{c}: recomputado '
                      f"tp={agg['tp'][c]} fn={agg['fn'][c]} fp={agg['fp'][c]} vs "
                      f"congelado tp={row['tp']} fn={row['fn']} fp={row['fp']}")
                ok = False
    return 'ok' if ok else 'DIVERGE'


def main():
    cfg = carregar_cfg()
    gab = carregar_gabarito(cfg)
    ph2col, _ = construir_de_para(cfg)
    res_dir = cfg['paths']['resultados_dir']

    linhas = []
    for saida in sorted(glob.glob(os.path.join(cfg['paths']['saida_dir'], '*.csv'))):
        tag = os.path.splitext(os.path.basename(saida))[0]
        _, stats, regs = stats_por_registro(saida, gab, ph2col)
        agg = agregar(stats)
        tp_t = sum(agg['tp'].values())
        fp_t = sum(agg['fp'].values())
        sobre = fp_t / (tp_t + fp_t) if tp_t + fp_t else 0.0
        pct_sub, ret = utilidade_texto(regs)
        rec_status = reconciliar(tag, agg, res_dir)
        linhas.append([tag, len(stats), f'{agg["recall_seguranca_macro"]:.4f}',
                       f'{agg["micro_f1"]:.4f}', f'{agg["micro_prec"]:.4f}',
                       tp_t, fp_t, f'{sobre:.4f}', f'{pct_sub:.4f}', f'{ret:.4f}',
                       rec_status])
        print(f'{tag:<34} n={len(stats)} sobre-remoção={sobre:.3f} '
              f'%texto_substituído={pct_sub:.3f} retenção={ret:.3f} '
              f'reconciliação={rec_status}')

    out = os.path.join(res_dir, 'metricas_utilidade.csv')
    with open(out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['config', 'n', 'recall_seguranca_macro', 'micro_f1', 'micro_prec',
                    'tp_total', 'fp_total', 'taxa_sobre_remocao',
                    'pct_texto_substituido', 'retencao_conteudo', 'reconciliacao'])
        w.writerows(linhas)
    print(f'\nSalvo em {out}')


if __name__ == '__main__':
    main()
