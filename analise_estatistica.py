"""
analise_estatistica.py — IC 95% por bootstrap e comparações pareadas (sem reexecutar modelos)
=============================================================================================
A partir dos resultados POR REGISTRO congelados em saidas/*.csv (996 BOs):

  1. Para CADA configuração: IC 95% por bootstrap (B = 10.000 réplicas, reamostrando
     os 996 BOs com reposição) para:
       - recall de segurança macro  (média, por tipo, de 1 - vazamentos/gold)
       - micro-F1
     As estimativas pontuais são reconciliadas com tabela_comparativa.csv.

  2. Comparação PAREADA (bootstrap pareado: mesmos índices de reamostragem nas duas
     configurações) entre as 3 do topo: hibrido_qwen3-8b (união),
     encadeado_qwen3-8b_llm_ner e llm_gemma3-12b — IC 95% da DIFERENÇA das métricas.
     Se o IC da diferença contém 0, as configurações são estatisticamente comparáveis
     no nível de 5%.

Saídas: resultados_avaliacao/bootstrap_ic.csv
        resultados_avaliacao/bootstrap_pareado_top3.csv
Uso:    python analise_estatistica.py [--B 10000] [--seed 42]
"""
import argparse
import csv
import glob
import os

import numpy as np

from eval_comum import (COLUNAS_PII, carregar_cfg, carregar_gabarito,
                        construir_de_para, stats_por_registro, agregar)

TOP3 = ['hibrido_qwen3-8b', 'encadeado_qwen3-8b_llm_ner', 'llm_gemma3-12b']


def stats_para_arrays(stats):
    """stats por registro -> arrays (n, 8) de tp, fn, fp, leak, gold."""
    n = len(stats)
    T = np.zeros((n, 8)); F = np.zeros((n, 8)); P = np.zeros((n, 8))
    L = np.zeros((n, 8)); G = np.zeros((n, 8))
    for i, st in enumerate(stats):
        for j, c in enumerate(COLUNAS_PII):
            t, f, p, l, g = st[c]
            T[i, j], F[i, j], P[i, j], L[i, j], G[i, j] = t, f, p, l, g
    return T, F, P, L, G


def metricas_de_somas(t, f, p, l, g):
    """t..g: arrays (B, 8) de somas por réplica -> (seg_macro, micro_f1), shape (B,)."""
    with np.errstate(divide='ignore', invalid='ignore'):
        seg = np.where(g > 0, 1.0 - l / g, np.nan)          # tipos ausentes na réplica: ignorados
        seg_macro = np.nanmean(seg, axis=1)
        mt, mf, mp = t.sum(1), f.sum(1), p.sum(1)
        rec = np.where(mt + mf > 0, mt / (mt + mf), 0.0)
        prec = np.where(mt + mp > 0, mt / (mt + mp), 0.0)
        f1 = np.where(rec + prec > 0, 2 * rec * prec / (rec + prec), 0.0)
    return seg_macro, f1


def bootstrap_somas(arrays, idx_chunks):
    """Para cada chunk de índices (B_chunk, n), soma por réplica. Gera (B,8) concatenado."""
    T, F, P, L, G = arrays
    outs = [[] for _ in range(5)]
    for idx in idx_chunks:
        for k, A in enumerate((T, F, P, L, G)):
            outs[k].append(A[idx].sum(axis=1))
    return [np.concatenate(o) for o in outs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--B', type=int, default=10000)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--chunk', type=int, default=500)
    args = ap.parse_args()

    cfg = carregar_cfg()
    gab = carregar_gabarito(cfg)
    ph2col, _ = construir_de_para(cfg)
    res_dir = cfg['paths']['resultados_dir']

    # ponto de reconciliação
    congelado = {}
    with open(os.path.join(res_dir, 'tabela_comparativa.csv'), encoding='utf-8') as f:
        for row in csv.DictReader(f):
            congelado[row['config']] = (float(row['recall_seguranca_macro']),
                                        float(row['micro_f1']))

    # carrega stats por registro de todas as configs
    dados = {}
    for saida in sorted(glob.glob(os.path.join(cfg['paths']['saida_dir'], '*.csv'))):
        tag = os.path.splitext(os.path.basename(saida))[0]
        _, stats, _ = stats_por_registro(saida, gab, ph2col)
        dados[tag] = stats_para_arrays(stats)
        agg = agregar(stats)
        seg0, f10 = agg['recall_seguranca_macro'], agg['micro_f1']
        cseg, cf1 = congelado.get(tag, (float('nan'), float('nan')))
        flag = 'ok' if (abs(seg0 - cseg) < 5e-4 and abs(f10 - cf1) < 5e-4) else 'DIVERGE'
        print(f'{tag:<34} ponto: seg={seg0:.4f} f1={f10:.4f} '
              f'(congelado {cseg:.4f}/{cf1:.4f}) [{flag}]')

    n = next(iter(dados.values()))[0].shape[0]
    rng = np.random.default_rng(args.seed)
    # MESMOS índices para todas as configs => bootstrap pareado por construção
    idx_chunks = [rng.integers(0, n, size=(min(args.chunk, args.B - i), n))
                  for i in range(0, args.B, args.chunk)]

    resultados = {}
    for tag, arrays in dados.items():
        t, f, p, l, g = bootstrap_somas(arrays, idx_chunks)
        seg, f1 = metricas_de_somas(t, f, p, l, g)
        resultados[tag] = (seg, f1)

    def ic(v):
        return np.percentile(v, 2.5), np.percentile(v, 97.5)

    # ---- CSV 1: ICs por configuração ----
    out1 = os.path.join(res_dir, 'bootstrap_ic.csv')
    with open(out1, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['config', 'B', 'seg_recall_ponto', 'seg_recall_ic95_inf',
                    'seg_recall_ic95_sup', 'micro_f1_ponto', 'micro_f1_ic95_inf',
                    'micro_f1_ic95_sup'])
        for tag, (seg, f1) in sorted(resultados.items()):
            cseg, cf1 = congelado.get(tag, (float('nan'), float('nan')))
            s_lo, s_hi = ic(seg); f_lo, f_hi = ic(f1)
            w.writerow([tag, args.B, f'{cseg:.4f}', f'{s_lo:.4f}', f'{s_hi:.4f}',
                        f'{cf1:.4f}', f'{f_lo:.4f}', f'{f_hi:.4f}'])
            print(f'{tag:<34} seg={cseg:.3f} IC[{s_lo:.3f},{s_hi:.3f}] | '
                  f'f1={cf1:.3f} IC[{f_lo:.3f},{f_hi:.3f}]')

    # ---- CSV 2: comparações pareadas top-3 ----
    out2 = os.path.join(res_dir, 'bootstrap_pareado_top3.csv')
    with open(out2, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['config_a', 'config_b', 'metrica', 'dif_media',
                    'dif_ic95_inf', 'dif_ic95_sup', 'contem_zero'])
        for i in range(len(TOP3)):
            for j in range(i + 1, len(TOP3)):
                a, b = TOP3[i], TOP3[j]
                for met, k in (('recall_seguranca_macro', 0), ('micro_f1', 1)):
                    d = resultados[a][k] - resultados[b][k]
                    lo, hi = ic(d)
                    zero = 'sim' if lo <= 0 <= hi else 'nao'
                    w.writerow([a, b, met, f'{d.mean():.4f}', f'{lo:.4f}',
                                f'{hi:.4f}', zero])
                    print(f'{a} - {b} | {met}: dif={d.mean():+.4f} '
                          f'IC[{lo:+.4f},{hi:+.4f}] contém 0: {zero}')

    print(f'\nSalvo em {out1} e {out2}')


if __name__ == '__main__':
    main()
