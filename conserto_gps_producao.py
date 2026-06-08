"""
conserto_gps_producao.py — Linha de produção corrigida (reconhecedor de coordenadas GPS)
========================================================================================
O reconhecedor de coordenadas DMS foi adicionado ao Estágio 1 APÓS o congelamento da
avaliação; os números da matriz comparativa não o refletem. Este script reexecuta
APENAS o Estágio 1 (regex, determinístico — única reexecução permitida) sobre os
textos de entrada da configuração recomendada (hibrido_qwen3-8b / união), mantém o
Estágio 2 congelado (lido do CSV), e reavalia a pipeline composta.

Saída: resultados_avaliacao/producao_corrigida_gps.csv (linha corrigida + congelada)
       + relatório das diferenças (coordenadas agora capturadas).
Uso:   python conserto_gps_producao.py
"""
import csv
import json
import os

from estagio1_regex import aplicar_estagio1
from eval_comum import (COLUNAS_PII, carregar_cfg, carregar_gabarito,
                        construir_de_para, stats_por_registro, agregar)

SAIDA = 'saidas_filtrado/hibrido_qwen3-8b.csv'


def main():
    cfg = carregar_cfg()
    gab = carregar_gabarito(cfg)
    ph2col, _ = construir_de_para(cfg)
    res_dir = cfg['paths']['resultados_dir']

    # 1) Reexecuta SOMENTE o Estágio 1 (regex atual, com COORDENADA) sobre os textos
    e1_novo = {}
    coords = []
    with open(SAIDA, encoding='utf-8') as f:
        for reg in csv.DictReader(f, delimiter=';'):
            seq = str(reg['Seq'])
            _, capturas = aplicar_estagio1(reg['texto_entrada'], retornar_capturas=True)
            e1_novo[seq] = {k: list(v) for k, v in capturas.items()}
            if capturas.get('COORDENADA'):
                coords.append((seq, list(capturas['COORDENADA'])))

    print(f'BOs com coordenadas GPS capturadas pelo Estágio 1 corrigido: {len(coords)}')
    for seq, c in coords:
        print(f'  Seq {seq}: {c}')

    # 2) Avalia: congelado (e1 do CSV) vs corrigido (e1 reexecutado + e2 congelado)
    _, stats_cong, _ = stats_por_registro(SAIDA, gab, ph2col)
    _, stats_corr, _ = stats_por_registro(SAIDA, gab, ph2col, e1_override=e1_novo)
    agg_c = agregar(stats_cong)
    agg_n = agregar(stats_corr)

    def fmt(agg):
        return (f"seg={agg['recall_seguranca_macro']:.4f} f1={agg['micro_f1']:.4f} "
                f"prec={agg['micro_prec']:.4f} "
                f"leak_local={agg['leak']['Localizações (s)']} "
                f"leak_total={sum(agg['leak'].values())}")

    print(f'\nCONGELADO : {fmt(agg_c)}')
    print(f'CORRIGIDO : {fmt(agg_n)}')
    print('\nVazamentos por tipo (congelado -> corrigido):')
    for c in COLUNAS_PII:
        if agg_c['leak'][c] != agg_n['leak'][c] or agg_c['fn'][c] != agg_n['fn'][c]:
            print(f'  {c}: leak {agg_c["leak"][c]} -> {agg_n["leak"][c]} | '
                  f'fn {agg_c["fn"][c]} -> {agg_n["fn"][c]} | '
                  f'fp {agg_c["fp"][c]} -> {agg_n["fp"][c]}')

    seg_local_c = 1 - agg_c['leak']['Localizações (s)'] / agg_c['gold']['Localizações (s)']
    seg_local_n = 1 - agg_n['leak']['Localizações (s)'] / agg_n['gold']['Localizações (s)']
    print(f'\n%% removido Localização: {100*seg_local_c:.1f}% -> {100*seg_local_n:.1f}%')

    out = os.path.join(res_dir, 'producao_corrigida_gps.csv')
    with open(out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['versao', 'recall_seguranca_macro', 'micro_f1', 'micro_prec',
                    'leak_total', 'leak_localizacao', 'pct_removido_localizacao'])
        w.writerow(['congelada_avaliacao', f"{agg_c['recall_seguranca_macro']:.4f}",
                    f"{agg_c['micro_f1']:.4f}", f"{agg_c['micro_prec']:.4f}",
                    sum(agg_c['leak'].values()), agg_c['leak']['Localizações (s)'],
                    f'{seg_local_c:.4f}'])
        w.writerow(['producao_corrigida_gps', f"{agg_n['recall_seguranca_macro']:.4f}",
                    f"{agg_n['micro_f1']:.4f}", f"{agg_n['micro_prec']:.4f}",
                    sum(agg_n['leak'].values()), agg_n['leak']['Localizações (s)'],
                    f'{seg_local_n:.4f}'])
    print(f'\nSalvo em {out}')


if __name__ == '__main__':
    main()
