"""
Estágio 1 — Anonimização determinística por REGEX (domínio: ROUBO)
===================================================================
Remove tudo que tem padrão estável, substituindo por placeholders tipados.
Estágio 1 de roubo: essencialmente a camada de remoção de PII estruturada.

  - PII estruturada é RARA no roubo (Tel ~1%, Doc ~2%, Placa ~4%); o peso está
    em Nome/Local, que são tratados no Estágio 2. Mesmo assim, telefone/CPF/RG/
    CNH/IMEI/placa/coordenada, quando aparecem, SÃO PII e devem ser removidos.
  - Formatos próprios do roubo, observados no gabarito auditado (996 BOs):
      * IMEI de celular subtraído: corrida de 15 dígitos (357576789999999).
      * Placa antiga (YNU-5948, EAI3782) E Mercosul (ABC1D23, LCD-2H39, PQR-1R15).
      * Telefones "sujos": (11)-948796214, (11)1234-56789, (11) 745431945.
      * VTR: A12345, M-12345, I-08960, "VTR 35".
      * Coordenadas GPS (DMS): 24°00'19.4"S 46°26'04.5"W.
      * Documentos heterogêneos no gabarito: RG, CPF, CNPJ, OAB/CRM, IMEI e
        ALGUNS códigos institucionais (BOPM, NOC, RE, processo CNJ).
  - marca/modelo de celular ou veículo (iPhone, Honda) NÃO é PII -> não remover.

A função principal `aplicar_estagio1` aplica as regex na ordem "mais específico
primeiro" e, opcionalmente, RETORNA as capturas por tipo (para o harness de
avaliação a nível de entidade).
"""

import re
import unicodedata
from collections import defaultdict

# =============================================================================
# DEFINIÇÃO DAS REGEX (justificada por classe)
# =============================================================================

# --- E-MAIL e CONTAS DE REDE SOCIAL ------------------------------------------
RE_EMAIL = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
# Arroba de rede social (@usuario); handles malformados como "@sebas348..".
RE_REDE_SOCIAL = re.compile(r'@[A-Za-z0-9._]{2,40}')
RE_URL = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+', re.IGNORECASE)

# --- REFERÊNCIAS INSTITUCIONAIS (higiene; fora das métricas de PII pessoal) --
RE_PROCESSO_CNJ = re.compile(r'\b\d{7}-?\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b')
RE_PROCESSO_ROTULADO = re.compile(
    r'(?i)(?:processo(?:\s+CNJ)?|autos?|inqu[ée]rito|IP|IPL)\s*(?:n[.ºo°]*\s*)?:?\s*[\d][\d./-]{4,}'
)
RE_PROTOCOLO = re.compile(r'(?i)protocolo\s*:?\s*(?:REQ)?[\dA-Z][\dA-Z./-]{4,}')
RE_BO_SPJ = re.compile(
    r'(?i)(?:boletim(?:\s+de\s+ocorr[êe]ncia)?|B\.?O\.?(?:\s*/?\s*PM)?|BOPM)\s*'
    r'(?:n[.ºo°]*\s*)?:?\s*(?:[A-Z]{2}\s?\d{4,5}(?:-\d)?(?:/\d{4})?|\d{4,})'
)
RE_OFICIO = re.compile(r'(?i)of[íi]cio\s*(?:n[.ºo°]*\s*)?:?\s*\d[\d/.]*(?:-[A-Za-z]+)?')
RE_CODIGO_INSTITUCIONAL = re.compile(
    r'(?i)\b(?:NOC|RE|RF|SAEP|RDO|COPOM|IML)\b\s*(?:-?\s*PESSOA)?\s*(?:n[.ºo°]*\s*)?:?\s*\d{4,}'
)

# --- DOCUMENTOS DE PESSOA FÍSICA ---------------------------------------------
RE_CNPJ = re.compile(r'\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b')
RE_REG_PROF = re.compile(r'(?i)\b(?:OAB|CRM|CREA|CRO|CRP)\s*[-/]?\s*[A-Z]{0,2}\s*n?[.ºo°]*\s*:?\s*\d{3,}')
RE_IMEI = re.compile(r'(?i)\bIMEI\s*:?\s*\d[\d.\s-]{10,}\d|\b\d{15}\b')
RE_CPF = re.compile(
    r'(?i)\bCPF\s*:?\s*\d{3}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?\d{2}\b'
    r'|\b\d{3}\.\d{3}\.\d{3}-\d{2}\b'
    r'|\b\d{11}\b'
)
RE_RG = re.compile(
    r'(?i)\bRG\s*:?\s*(?:n[.ºo°]*\s*)?[\d][\d.\s-]{4,12}[-]?[\dXx]?\b'
    r'|\b\d{1,2}\.\d{3}\.\d{3}-[\dXx]{1,3}\b'
    r'|\b\d{7,8}-[\dXx]\b'
)
RE_CNH = re.compile(r'(?i)\bCNH\s*:?\s*\d{9,11}\b')

# --- TELEFONES (vários formatos, recalibrados ao "sujo" do roubo) ------------
RE_TELEFONE = re.compile(
    r'\(?\b0?[1-9][0-9]\)?\s*[-.]?\s*(?:9\s*\d{4}|\d{4,5})[-.\s]?\d{4,5}\b'
)
RE_TELEFONE_ROTULADO = re.compile(
    r'(?i)(?:telefone|fone|cel(?:ular)?|whats(?:app)?)\s*:?\s*'
    r'(?:\(?\d{2,3}\)?\s*)?(?:9\s*)?\d{4,5}[-.\s]?\d{4}'
)
RE_TELEFONE_INTL = re.compile(r'\+\d{1,3}\s*\d[\d\s.()-]{7,}')

# --- DATAS -------------------------------------------------------------------
RE_DATA_EXTENSO = re.compile(
    r'(?i)\b\d{1,2}\s+de\s+(?:janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|'
    r'agosto|setembro|outubro|novembro|dezembro)\s+de\s+\d{4}'
)
RE_DATA_BARRA = re.compile(r'\b\d{2}/\d{2}/\d{2,4}\b')
RE_DATA_PONTO_HIFEN = re.compile(r'\b\d{2}[.-]\d{2}[.-]\d{2,4}\b')

# --- VIATURAS (VTR) ----------------------------------------------------------
RE_VIATURA_CODIGO = re.compile(r'\b[A-Z]-?\d{5}\b')
RE_VIATURA_ROTULADO = re.compile(
    r'(?i)(?:viatura|VTR)\s*(?:de\s+)?(?:prefixo\s+)?(?:n[.ºo°]*\s*)?(?:[A-Z]{1,5}\s+)?[A-Z]{0,2}-?\d{1,5}'
)

# --- PLACAS DE VEÍCULO -------------------------------------------------------
# Cobre antiga (YNU-5948, EAI3782) e Mercosul (ABC1D23, LCD-2H39, PQR-1R15).
RE_PLACA = re.compile(r'\b[A-Z]{3}-?\d[A-Z0-9]\d{2}\b')

# --- CEP ---------------------------------------------------------------------
RE_CEP = re.compile(r'\b\d{5}-?\d{3}\b')

# --- COORDENADAS GPS (DMS) ---------------------------------------------------
# Localização precisa = PII sensível. Formato observado no corpus:
# 24°00'19.4"S 46°26'04.5"W. Casa cada componente (grau/min/seg + hemisfério),
# tolerante a aspas tipográficas e espaços. Aplicado ANTES da varredura genérica.
RE_COORDENADA = re.compile(
    r'\d{1,3}\s*°\s*\d{1,2}\s*[\'′]\s*[\d.]+\s*["″”]\s*[NSEWnsew]'
)

# --- ENDEREÇO (logradouro com prefixo) ---------------------------------------
RE_ENDERECO = re.compile(
    r'\b(?:Rua|R\.|Avenida|Av\.|Alameda|Al\.|Travessa|Trav\.|Estrada|Estr\.|'
    r'Rodovia|Rod\.|Pra[çc]a|P[çc]\.|Viela|Vila|Largo)\s+'
    r'[A-ZÀ-Ú][^\n,;]{2,50}(?:\s*,\s*(?:n[.ºo°]*\s*)?\d+)?'
)

# --- VARREDURA GENÉRICA DE RESCALDO ------------------------------------------
RE_ALFANUM_CONCAT = re.compile(r'\b[A-Z]{2,}\d{4,}\b|\b\d{4,}[A-Z]{1,3}\b')
RE_NUMERO_LONGO = re.compile(r'\b\d{6,}\b')   # códigos longos residuais


# =============================================================================
# APLICAÇÃO ORDENADA (mais específico primeiro) com registro de capturas
# =============================================================================
def aplicar_estagio1(texto, retornar_capturas=False):
    """Aplica o Estágio 1 (regex) ao texto. Se retornar_capturas=True, devolve
    também {placeholder: [spans capturados]} (para o harness de avaliação)."""
    if not texto or not str(texto).strip():
        return ('', {}) if retornar_capturas else ''

    texto = str(texto)
    capturas = defaultdict(list)

    def sub(regex, placeholder_nome):
        nonlocal texto
        def _rep(m):
            capturas[placeholder_nome].append(m.group())
            return f'[{placeholder_nome}]'
        texto = regex.sub(_rep, texto)

    # ── Camada 1: e-mail, redes sociais, URLs ──
    sub(RE_URL, 'URL')
    sub(RE_EMAIL, 'EMAIL')

    # ── Camada 2: referências institucionais (higiene) ──
    sub(RE_PROCESSO_CNJ, 'PROCESSO')
    sub(RE_PROCESSO_ROTULADO, 'PROCESSO')
    sub(RE_PROTOCOLO, 'PROTOCOLO')
    sub(RE_BO_SPJ, 'BO')
    sub(RE_OFICIO, 'OFICIO')
    sub(RE_CODIGO_INSTITUCIONAL, 'CODIGO')

    # ── Camada 3: documentos de pessoa física ──
    sub(RE_CNPJ, 'CPF')
    sub(RE_REG_PROF, 'REG_PROF')
    sub(RE_IMEI, 'IMEI')         # 15 dígitos ANTES de CPF (11) e telefone
    sub(RE_CPF, 'CPF')
    sub(RE_RG, 'RG')
    sub(RE_CNH, 'CNH')

    # ── Camada 4: telefones ──
    sub(RE_TELEFONE_INTL, 'TELEFONE')
    sub(RE_TELEFONE_ROTULADO, 'TELEFONE')
    sub(RE_TELEFONE, 'TELEFONE')

    # ── Camada 5: datas ──
    sub(RE_DATA_EXTENSO, 'DATA')
    sub(RE_DATA_BARRA, 'DATA')
    sub(RE_DATA_PONTO_HIFEN, 'DATA')

    # ── Camada 6: viaturas e placas ──
    sub(RE_VIATURA_ROTULADO, 'VIATURA')
    sub(RE_VIATURA_CODIGO, 'VIATURA')
    sub(RE_PLACA, 'PLACA')

    # ── Camada 7: rede social (@handle) depois de e-mail/placa ──
    sub(RE_REDE_SOCIAL, 'REDE_SOCIAL')

    # ── Camada 8: coordenadas GPS, CEP e endereço ──
    sub(RE_COORDENADA, 'COORDENADA')
    sub(RE_CEP, 'CEP')
    sub(RE_ENDERECO, 'ENDERECO')

    # ── Camada 9: varredura genérica com PROTEÇÃO de referências legais ──
    leis_protegidas = []
    def proteger_lei(m):
        leis_protegidas.append(m.group())
        return f'__LEI_{len(leis_protegidas)-1}__'
    texto = re.sub(
        r'(?i)(?:lei|decreto[-\s]?lei)\s*'
        r'(?:(?:federal|estadual|municipal|complementar|n[.ºo°]*)\s*)*:?\s*[\d][\d.]+/\d{2,4}',
        proteger_lei, texto)
    texto = re.sub(
        r'(?i)\bart\.?\s*\d+[°ºª]?\s*(?:,?\s*(?:§|inciso|al[íi]nea|par[áa]grafo|caput)\s*[^,;.]{0,30})?',
        proteger_lei, texto)

    sub(RE_ALFANUM_CONCAT, 'CODIGO')
    sub(RE_NUMERO_LONGO, 'CODIGO')

    for i, lei in enumerate(leis_protegidas):
        texto = texto.replace(f'__LEI_{i}__', lei)

    # ── Limpeza final: placeholders duplicados adjacentes ──
    texto = re.sub(r'(\[(?:TELEFONE|RG|CPF|IMEI|DATA|CODIGO|BO|VIATURA|PLACA|COORDENADA)\])(\s*\1)+', r'\1', texto)
    texto = re.sub(r'  +', ' ', texto)

    if retornar_capturas:
        return texto, dict(capturas)
    return texto


# =============================================================================
# Utilidades de normalização (compartilhadas com o harness)
# =============================================================================
def normalizar(s):
    """Casamento robusto: minúsculas, sem acento, sem pontuação/espaço extra."""
    s = str(s).strip().lower()
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r'[^\w]', '', s)
    return s


if __name__ == '__main__':
    exemplos = [
        "Presente Maria Regina, IMEI 357576789999999, placa YNU-5948 e ABC1D23, "
        "tel (11) 95874-1452, RG 23.421.591-6, viatura A12345, art. 157 do CP.",
        "Local 24°00'19.4\"S 46°26'04.5\"W e tambem 23°39'20.0\"S 46°41'08.6\"W.",
    ]
    for ex in exemplos:
        out, caps = aplicar_estagio1(ex, retornar_capturas=True)
        print("DEPOIS:", out)
        print("CAPS  :", dict(caps))
        print()
