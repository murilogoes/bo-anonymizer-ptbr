"""
Estágio 2 — Camada semântica PLUGÁVEL (domínio: ROUBO)
=======================================================
Detecta o que a regex não pega: nomes de pessoas, localizações nomeadas
(bairros/logradouros/cidades), estabelecimentos/POIs nomeados e vulgos.

Arquitetura: um contrato único `MotorEstagio2` com back-ends intercambiáveis,
selecionados por uma factory a partir do config/CLI. TODOS os motores devolvem
o MESMO formato de saída (dict de entidades), e a substituição local é
compartilhada — assim a comparação isola apenas a qualidade da EXTRAÇÃO.

Contrato:
    motor.extrair(texto) -> {"nomes": [...], "locais": [...],
                             "estabelecimentos": [...], "vulgos": [...]}

Back-ends:
    regex_only : no-op (baseline; só o Estágio 1 age)
    ner        : spaCy pt_core_news_lg | BERTimbau-NER  (PER/LOC/ORG -> tipos)
    llm        : Ollama (Qwen/Llama/Gemma) — extrai JSON, estratégia da v2 do VDM
    hibrido    : união NER ∪ LLM
    encadeado  : aplica um motor, depois o outro (ordem configurável)
    presidio   : baseline de SISTEMA (recomendação B) — Presidio out-of-the-box

Reaproveita do VDM (anonimizar_narrativas_v2.py): substituição local ordenada
por comprimento, numeração por aparição (coreferência) e o FILTRO de exclusão —
aqui RECALIBRADO para roubo (papéis processuais e descritores genéricos do
domínio: indivíduo, autor 1/2, carona, comparsa, condutor, suspeito, guarnição…).

Cada motor expõe `ultimo_prompt_tokens`/`ultimo_completion_tokens` (custo por
registro; 0 para motores sem LLM). Compostos somam os tokens dos sub-motores.

Imports pesados (spacy/transformers/requests/presidio) são preguiçosos: o
baseline regex_only e a camada de substituição funcionam sem eles instalados.
"""

import re
import json
import unicodedata
from abc import ABC, abstractmethod

# Reutiliza a normalização do Estágio 1 (casamento robusto)
from estagio1_regex import normalizar


# =============================================================================
# FILTROS DE EXCLUSÃO — RECALIBRADOS PARA ROUBO
# =============================================================================
# Diferença-chave vs VDM: no roubo os falsos-positivos de "nome" são sobretudo
# PAPÉIS PROCESSUAIS e DESCRITORES GENÉRICOS de pessoa, não parentesco. Mantemos
# o núcleo de parentesco/pronomes do VDM (ainda válido) e ADICIONAMOS o léxico
# do roubo.

EXCLUSAO_NOMES = {
    # Pronomes
    'ele', 'ela', 'eu', 'mim', 'nós', 'eles', 'elas', 'dele', 'dela',
    'me', 'te', 'se', 'nos', 'lhe', 'lhes', 'si',
    'Ele', 'Ela', 'Eu', 'Nós', 'Eles', 'Elas',
    # Papéis processuais / descritores de pessoa (NÚCLEO DO ROUBO)
    'vítima', 'vitima', 'vítimas', 'vitimas',
    'autor', 'autora', 'autores', 'autor 1', 'autor 2', 'autor1', 'autor2',
    'autor 01', 'autor 02', 'primeiro autor', 'segundo autor',
    'declarante', 'comunicante', 'noticiante', 'requerente', 'requerido',
    'indiciado', 'indiciada', 'averiguado', 'averiguada',
    'suspeito', 'suspeita', 'suspeitos', 'suspeitas',
    'acusado', 'acusada', 'investigado', 'investigada',
    'meliante', 'meliantes', 'infrator', 'infratora',
    'criminoso', 'criminosos', 'assaltante', 'assaltantes', 'ladrão', 'ladrao',
    'roubador', 'agente', 'agentes',
    # Genéricos de pessoa (muito comuns no roubo)
    'indivíduo', 'individuo', 'indivíduos', 'individuos',
    'cidadão', 'cidadao', 'cidadã', 'cidada', 'cidadãos',
    'rapaz', 'homem', 'mulher', 'moça', 'moca', 'pessoa', 'pessoas',
    'transeunte', 'pedestre', 'abordado', 'abordada', 'abordados',
    'comparsa', 'comparsas', 'capanga', 'compartícipe',
    'carona', 'garupa', 'piloto', 'condutor', 'condutora', 'motorista',
    'passageiro', 'passageira', 'ocupante', 'ocupantes',
    'menor', 'menores', 'adolescente', 'adolescentes', 'criança', 'crianca',
    'testemunha', 'testemunhas', 'denunciante',
    # Forças de segurança (PAPEL é genérico; o SOBRENOME do PM é nome e fica)
    'policial', 'policiais', 'guarnição', 'guarnicao', 'equipe', 'viatura',
    'delegado', 'delegada', 'escrivão', 'escrivao', 'escrivã',
    'investigador', 'investigadora', 'inspetor', 'inspetora', 'comandante',
    'soldado', 'sargento', 'cabo', 'tenente', 'capitão', 'capitao',
    'guarda', 'gcm', 'pm', 'vigilante', 'segurança', 'seguranca', 'porteiro',
    # Tratamento
    'senhor', 'senhora', 'sr', 'sra', 'dona', 'dr', 'dra',
    'Senhor', 'Senhora', 'Dona',
    # Parentesco (núcleo herdado do VDM — ainda ocorre)
    'filho', 'filha', 'mãe', 'mae', 'pai', 'irmão', 'irmã', 'irmao', 'irma',
    'tio', 'tia', 'primo', 'prima', 'avô', 'avó', 'avo', 'neto', 'neta',
    'marido', 'esposa', 'esposo', 'companheiro', 'companheira',
    'namorado', 'namorada', 'sogro', 'sogra', 'cunhado', 'cunhada',
    'amigo', 'amiga', 'vizinho', 'vizinha', 'colega', 'patrão', 'patrao',
}

# Locais genéricos (reaproveitado do VDM; válido para roubo)
EXCLUSAO_LOCAIS = {
    'casa', 'residência', 'residencia', 'domicílio', 'domicilio',
    'apartamento', 'apto', 'imóvel', 'imovel', 'condomínio', 'condominio',
    'prédio', 'predio', 'edifício', 'edificio', 'quarto', 'sala', 'cozinha',
    'banheiro', 'quintal', 'garagem', 'varanda', 'portaria', 'estacionamento',
    'rua', 'avenida', 'travessa', 'alameda', 'viela', 'beco', 'estrada',
    'rodovia', 'via pública', 'via publica', 'calçada', 'calcada', 'esquina',
    'praça', 'praca', 'parque', 'jardim', 'ponto de ônibus', 'ponto de onibus',
    'terminal', 'ponto', 'semáforo', 'semaforo', 'cruzamento',
    'hospital', 'pronto socorro', 'pronto-socorro', 'ps', 'ubs', 'upa',
    'delegacia', 'dp', 'plantão', 'plantao', 'batalhão', 'batalhao', 'quartel',
    'escola', 'creche', 'faculdade', 'universidade', 'igreja', 'bar', 'boteco',
    'lanchonete', 'restaurante', 'padaria', 'mercado', 'supermercado',
    'farmácia', 'farmacia', 'loja', 'lojas', 'comércio', 'comercio', 'oficina',
    'salão', 'salao', 'academia', 'motel', 'hotel', 'posto', 'posto de gasolina',
    'shopping', 'agência', 'agencia', 'banco', 'caixa', 'estabelecimento',
    'trabalho', 'serviço', 'servico', 'firma', 'empresa', 'escritório',
    'comércio local', 'via', 'local', 'estabelecimento comercial',
}
EXCLUSAO_ESTABELECIMENTOS = set(EXCLUSAO_LOCAIS)

# Marcas/modelos de celular e veículo: NÃO são PII no roubo (descrição de objeto
# subtraído). Excluídos de nomes/estabelecimentos para evitar sobre-remoção.
EXCLUSAO_MARCAS = {
    'iphone', 'samsung', 'galaxy', 'motorola', 'moto g', 'xiaomi', 'redmi',
    'nokia', 'lg', 'apple', 'asus', 'positivo', 'multilaser',
    'honda', 'yamaha', 'suzuki', 'fiat', 'volkswagen', 'vw', 'chevrolet', 'gm',
    'ford', 'toyota', 'hyundai', 'renault', 'nissan', 'jeep', 'cg', 'cb', 'biz',
    'fan', 'titan', 'pop', 'corinthians', 'palmeiras', 'são paulo', 'santos',
}

# Padrões regex de parentesco/genérico (complementam a lista estática)
RE_PARENTESCO_PATTERNS = [
    re.compile(r'^(meu|minha|meus|minhas|seu|sua|seus|suas|nosso|nossa)\b', re.I),
    re.compile(r'^ex[\s\-]', re.I),
    re.compile(r'^(autor|indiv[íi]duo|suspeito|comparsa|elemento)\s*\d+$', re.I),
    re.compile(r'^(primeiro|segundo|terceiro)\s+(autor|indiv[íi]duo|suspeito)$', re.I),
]


# =============================================================================
# FILTRAGEM DE ENTIDADES
# =============================================================================
def _no_conjunto(valor, conjunto):
    if valor in conjunto:
        return True
    vl = valor.lower()
    return any(item.lower() == vl for item in conjunto)


def _is_parentesco(texto):
    return any(p.search(texto) for p in RE_PARENTESCO_PATTERNS)


# Palavras que são NOMES de placeholders do Estágio 1/2 — o NER às vezes tagueia
# o miolo de "[PLACA]"/"[CODIGO]" como entidade; nunca devem virar entidade
# (senão a substituição corromperia o placeholder já existente).
PLACEHOLDER_WORDS = {
    'NOME', 'LOCAL', 'ESTABELECIMENTO', 'VULGO', 'TELEFONE', 'EMAIL',
    'REDE_SOCIAL', 'URL', 'PROCESSO', 'PROTOCOLO', 'BO', 'INQUERITO', 'OFICIO',
    'CODIGO', 'CPF', 'RG', 'CNH', 'IMEI', 'REG_PROF', 'DATA', 'VIATURA',
    'PLACA', 'CEP', 'ENDERECO',
}


def _eh_token_placeholder(s):
    """True se s é/contém um token de placeholder (ex.: 'PLACA', '[CEP]')."""
    if '[' in s or ']' in s:
        return True
    return s.strip().upper().strip('[]') in PLACEHOLDER_WORDS


def filtrar_entidades(ent):
    """Remove pronomes, papéis/genéricos, marcas e ruído. Retorna (dict, n_removidos)."""
    rem = 0
    out = {'nomes': [], 'locais': [], 'estabelecimentos': [], 'vulgos': []}

    for nome in ent.get('nomes', []):
        s = nome.strip()
        if _eh_token_placeholder(s) or _no_conjunto(s, EXCLUSAO_NOMES) \
           or _no_conjunto(s, EXCLUSAO_MARCAS) or len(s) < 2 or _is_parentesco(s):
            rem += 1
            continue
        out['nomes'].append(s)

    for loc in ent.get('locais', []):
        s = loc.strip()
        if _eh_token_placeholder(s) or _no_conjunto(s, EXCLUSAO_LOCAIS) or len(s) < 2:
            rem += 1
            continue
        # local de uma só palavra minúscula => provavelmente genérico
        if ' ' not in s and s[:1].islower():
            rem += 1
            continue
        out['locais'].append(s)

    for est in ent.get('estabelecimentos', []):
        s = est.strip()
        if _eh_token_placeholder(s) or _no_conjunto(s, EXCLUSAO_ESTABELECIMENTOS) \
           or _no_conjunto(s, EXCLUSAO_MARCAS) or len(s) < 2:
            rem += 1
            continue
        if ' ' not in s and s[:1].islower():
            rem += 1
            continue
        out['estabelecimentos'].append(s)

    for v in ent.get('vulgos', []):
        s = v.strip()
        if _eh_token_placeholder(s) or len(s) < 2 or _no_conjunto(s, EXCLUSAO_NOMES):
            rem += 1
            continue
        out['vulgos'].append(s)

    return out, rem


# =============================================================================
# SUBSTITUIÇÃO LOCAL COMPARTILHADA (idêntica para todos os motores)
# =============================================================================
PLACEHOLDER_POR_CATEGORIA = {
    'nomes': 'NOME',
    'locais': 'LOCAL',
    'estabelecimentos': 'ESTABELECIMENTO',
    'vulgos': 'VULGO',
}


def aplicar_substituicoes(texto, entidades, numerar=True):
    """Substitui entidades por placeholders, ordenando por comprimento decrescente.

    numerar=True preserva coreferência ([NOME_1] = mesma pessoa). A avaliação
    NÃO depende da numeração: o harness compara as STRINGS extraídas, não o texto.

    Retorna (texto_anonimizado, n_substituicoes).
    """
    if not entidades:
        return texto, 0

    subs = []
    for categoria, prefixo in PLACEHOLDER_POR_CATEGORIA.items():
        itens = entidades.get(categoria, [])
        com_pos = []
        for ent in itens:
            if len(ent) < 2:
                continue
            m = re.search(r'(?<![0-9A-Za-z\u00c0-\u00ff])' + re.escape(ent) +
                          r'(?![0-9A-Za-z\u00c0-\u00ff])', texto, re.IGNORECASE)
            if m:
                com_pos.append((m.start(), ent))
        com_pos.sort(key=lambda x: x[0])
        for i, (pos, ent) in enumerate(com_pos, 1):
            ph = f'[{prefixo}_{i}]' if numerar else f'[{prefixo}]'
            subs.append((ent, ph))

    subs.sort(key=lambda x: len(x[0]), reverse=True)

    # Protege placeholders já existentes ([PLACA], [CODIGO], [NOME_1]...) trocando-os
    # por sentinelas antes das substituições, restaurando ao final. Garante que o
    # Estágio 2 nunca corrompa placeholders do Estágio 1 nem os seus próprios.
    existentes = re.findall(r'\[[A-Z_]+\d*\]', texto)
    sentinela = {}
    res = texto
    for i, ph_exist in enumerate(dict.fromkeys(existentes)):
        s = f'\x00{i}\x00'
        sentinela[s] = ph_exist
        res = res.replace(ph_exist, s)

    n = 0
    for ent, ph in subs:
        if '\x00' in ent or '[' in ent or ']' in ent:
            continue  # nunca substituir algo que toca sentinela/placeholder
        pat = re.compile(r'(?<![0-9A-Za-z\u00c0-\u00ff])' + re.escape(ent) +
                         r'(?![0-9A-Za-z\u00c0-\u00ff])', re.IGNORECASE)
        res, c = pat.subn(ph, res)
        n += c

    for s, ph_exist in sentinela.items():
        res = res.replace(s, ph_exist)
    return res, n


# =============================================================================
# CONTRATO + FACTORY
# =============================================================================
def _vazio():
    return {'nomes': [], 'locais': [], 'estabelecimentos': [], 'vulgos': []}


class MotorEstagio2(ABC):
    """Contrato único. Todos os back-ends devolvem o mesmo dict de entidades."""
    nome = 'base'
    ultimo_prompt_tokens = 0        # custo por registro (0 p/ motores sem LLM)
    ultimo_completion_tokens = 0

    @abstractmethod
    def _extrair_bruto(self, texto):
        """Retorna dict de entidades CRU (antes do filtro)."""
        ...

    def extrair(self, texto):
        """Extrai + filtra. Saída pronta para a substituição compartilhada."""
        if not texto or not str(texto).strip():
            return _vazio()
        bruto = self._extrair_bruto(str(texto))
        filtrado, _ = filtrar_entidades(bruto)
        return filtrado


class MotorRegexOnly(MotorEstagio2):
    """Baseline: o Estágio 1 já fez tudo; o Estágio 2 não acrescenta nada."""
    nome = 'regex_only'

    def _extrair_bruto(self, texto):
        return _vazio()


# ---------------------------------------------------------------------------
# NER (spaCy / BERTimbau) — imports preguiçosos
# ---------------------------------------------------------------------------
# Mapa de labels do NER -> categorias do gabarito.
#   PER -> nomes ; LOC/GPE -> locais ; ORG -> estabelecimentos ; MISC -> ignora
# Vulgo é subcaso de PER quando o NER não distingue (LIMITAÇÃO documentada).
MAPA_LABELS = {
    'PER': 'nomes', 'PERSON': 'nomes', 'PESSOA': 'nomes',
    'LOC': 'locais', 'GPE': 'locais', 'LOCAL': 'locais', 'LOCALIZACAO': 'locais',
    'ORG': 'estabelecimentos', 'ORGANIZACAO': 'estabelecimentos',
}


def _chunk_para_ner(texto, max_chars=450):
    """Divide o texto em blocos curtos (fronteira de sentença) para não estourar
    o limite de 512 tokens do BERT. Sentenças gigantes são fatiadas à força.
    spaCy não precisa disso (lida com docs longos); só o BERTimbau/transformers."""
    if len(texto) <= max_chars:
        return [texto]
    sentencas = re.split(r'(?<=[.!?])\s+', texto)
    blocos, atual = [], ''
    for s in sentencas:
        while len(s) > max_chars:          # sentença isolada maior que o limite
            if atual:
                blocos.append(atual)
                atual = ''
            blocos.append(s[:max_chars])
            s = s[max_chars:]
        if len(atual) + len(s) + 1 <= max_chars:
            atual = (atual + ' ' + s).strip()
        else:
            if atual:
                blocos.append(atual)
            atual = s
    if atual:
        blocos.append(atual)
    return blocos


class MotorNER(MotorEstagio2):
    """NER dedicado local. backend='spacy' ou 'bertimbau'."""

    def __init__(self, cfg, backend='spacy', modelo=None):
        self.nome = f'ner:{backend}'
        self.backend = backend
        self.cfg = cfg
        self.modelo = modelo
        self._nlp = None
        self._pipe = None
        self.ultimo_prompt_tokens = 0
        self.ultimo_completion_tokens = 0

    def _load(self):
        if self.backend == 'spacy':
            import spacy
            nome_modelo = self.modelo or self.cfg['ner']['spacy_model']
            self._nlp = spacy.load(nome_modelo)
        elif self.backend == 'bertimbau':
            from transformers import (AutoTokenizer,
                                      AutoModelForTokenClassification, pipeline)
            ckpt = self.modelo or self.cfg['ner']['bertimbau_ner_checkpoint']
            tok = AutoTokenizer.from_pretrained(ckpt)
            tok.model_max_length = 512                # rede de segurança p/ o limite do BERT
            mdl = AutoModelForTokenClassification.from_pretrained(ckpt)
            dev = 0 if self.cfg['ner'].get('device') == 'cuda' else -1
            self._pipe = pipeline('ner', model=mdl, tokenizer=tok,
                                  aggregation_strategy='simple', device=dev)
        else:
            raise ValueError(f'backend NER desconhecido: {self.backend}')

    def _extrair_bruto(self, texto):
        ent = _vazio()
        if self.backend == 'spacy':
            if self._nlp is None:
                self._load()
            for e in self._nlp(texto).ents:
                cat = MAPA_LABELS.get(e.label_.upper())
                if cat:
                    ent[cat].append(e.text)
        else:  # bertimbau / transformers
            if self._pipe is None:
                self._load()
            # Fatiar em blocos < 512 tokens (BERT) antes de passar ao pipeline
            for chunk in _chunk_para_ner(texto):
                for e in self._pipe(chunk):
                    lbl = e.get('entity_group', e.get('entity', '')).upper()
                    lbl = lbl.split('-')[-1]  # tira prefixo B-/I-
                    cat = MAPA_LABELS.get(lbl)
                    if cat:
                        ent[cat].append(e['word'])
        return ent


# ---------------------------------------------------------------------------
# LLM (Ollama) — imports preguiçosos. Reusa a estratégia da v2 do VDM.
# ---------------------------------------------------------------------------
def _apenas_presentes(ent, texto):
    """Anti-eco: descarta spans ausentes do texto (p.ex. exemplos do prompt)."""
    tn = normalizar(texto)
    out = {}
    for k, v in ent.items():
        out[k] = ([s for s in v if normalizar(s) and normalizar(s) in tn]
                  if isinstance(v, list) else v)
    return out


SYSTEM_PROMPT_ROUBO = """Extraia APENAS nomes próprios reais de pessoas, locais nomeados, estabelecimentos nomeados e vulgos/apelidos de um boletim de ocorrência de ROUBO.

IMPORTANTE: extraia SOMENTE termos que apareçam LITERALMENTE no texto recebido. Os exemplos marcados com "SIM" abaixo ilustram apenas o FORMATO e jamais devem ser copiados para a resposta.

NOMES — SOMENTE nomes próprios reais de pessoa (inclui sobrenomes de policiais):
SIM: "Esdras Alves Da Silva", "Maria Regina", "Costa", "Guimarães"
NUNCA: vítima, autor, autor 1, autor 2, indivíduo, cidadão, suspeito, comparsa, carona, garupa, condutor, motorista, meliante, assaltante, declarante, testemunha, policial, guarnição, senhor, senhora; pronomes (ele/ela); parentesco (filho, mãe, irmão, marido, esposa).

LOCAIS — bairros, logradouros nomeados e cidades:
SIM: "Vila Mariana", "Av. Dos Lagos", "Piracicamirin", "Jardim Europa"
NUNCA: rua, avenida, casa, residência, esquina, ponto de ônibus, delegacia, hospital, comércio, estabelecimento (sem nome próprio).

ESTABELECIMENTOS — SOMENTE com nome próprio identificável:
SIM: "Prato Feliz", "Shopping Botelho", "Mercado São Jorge"
NUNCA: mercado, loja, bar, posto, farmácia, padaria (sem nome).

VULGOS/APELIDOS de criminosos:
SIM: "Tubarão", "Zé Pequeno", "vulgo Magrão"

REGRAS:
1. Copie cada entidade EXATAMENTE como no texto.
2. Marca/modelo de celular ou veículo (iPhone, Samsung, Honda, Yamaha) NÃO é entidade.
3. Na dúvida entre nome próprio e papel/genérico, NÃO inclua.
4. NUNCA inclua estados ou países.

Retorne SOMENTE JSON: {"nomes": [], "locais": [], "estabelecimentos": [], "vulgos": []}"""


def extrair_json_llm(resp):
    """Parsing tolerante do JSON do modelo (markdown, <think>, lixo ao redor)."""
    if not resp:
        return None
    resp = re.sub(r'<think>.*?</think>', '', resp, flags=re.DOTALL).strip()
    resp = re.sub(r'```json\s*|```\s*', '', resp).strip()
    m = re.search(r'\{.*\}', resp, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group())
    except (json.JSONDecodeError, ValueError):
        return None
    out = _vazio()
    for k in out:
        v = obj.get(k, [])
        if isinstance(v, list):
            out[k] = [s.strip() for s in v if isinstance(s, str) and s.strip()]
        elif isinstance(v, str) and v.strip():
            out[k] = [v.strip()]
    return out


class MotorLLM(MotorEstagio2):
    """LLM local via Ollama (API nativa /api/chat, think=false). --modelo configurável."""

    def __init__(self, cfg, modelo=None):
        self.cfg = cfg
        self.modelo = modelo or cfg['llm']['modelos'][0]
        self.nome = f'llm:{self.modelo}'
        l = cfg['llm']
        self.url = f"http://{l['host']}:{l['porta']}/api/chat"
        self._session = None
        self.ultimo_prompt_tokens = 0
        self.ultimo_completion_tokens = 0

    def _sess(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def _chamar(self, texto):
        l = self.cfg['llm']
        payload = {
            'model': self.modelo,
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT_ROUBO},
                {'role': 'user', 'content': texto},
            ],
            'stream': False,
            'think': l.get('think', False),
            'options': {'temperature': l.get('temperature', 0.1),
                        'num_predict': l.get('max_tokens', 512)},
        }
        r = self._sess().post(self.url, json=payload, timeout=l.get('timeout_s', 300))
        r.raise_for_status()
        data = r.json()
        # Tokens de custo (API nativa do Ollama)
        self.ultimo_prompt_tokens = data.get('prompt_eval_count', 0)
        self.ultimo_completion_tokens = data.get('eval_count', 0)
        return data.get('message', {}).get('content', '')

    def _extrair_bruto(self, texto):
        self.ultimo_prompt_tokens = 0
        self.ultimo_completion_tokens = 0
        l = self.cfg['llm']
        for tent in range(l.get('max_retries', 3)):
            try:
                ent = extrair_json_llm(self._chamar(texto))
                if ent is not None:
                    return _apenas_presentes(ent, texto)
            except Exception:
                pass
        return _vazio()  # fallback: nada extraído (registra-se à parte no pipeline)


# ---------------------------------------------------------------------------
# Presidio — baseline de SISTEMA (recomendação B), imports preguiçosos
# ---------------------------------------------------------------------------
class MotorPresidio(MotorEstagio2):
    """Presidio out-of-the-box (analyzer + spaCy). Mede o PACOTE pronto, não a
    detecção pura (o NER por baixo é o mesmo spaCy avaliado isolado)."""
    nome = 'presidio'

    def __init__(self, cfg):
        self.cfg = cfg
        self._analyzer = None
        self.ultimo_prompt_tokens = 0
        self.ultimo_completion_tokens = 0

    def _load(self):
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        p = self.cfg['presidio']
        provider = NlpEngineProvider(nlp_configuration={
            'nlp_engine_name': p.get('nlp_engine', 'spacy'),
            'models': [{'lang_code': p.get('idioma', 'pt'),
                        'model_name': p.get('spacy_model', 'pt_core_news_lg')}],
        })
        self._analyzer = AnalyzerEngine(nlp_engine=provider.create_engine(),
                                        supported_languages=[p.get('idioma', 'pt')])

    _MAP = {'PERSON': 'nomes', 'LOCATION': 'locais', 'GPE': 'locais',
            'NRP': 'nomes', 'ORGANIZATION': 'estabelecimentos', 'ORG': 'estabelecimentos'}

    def _extrair_bruto(self, texto):
        if self._analyzer is None:
            self._load()
        ent = _vazio()
        res = self._analyzer.analyze(text=texto,
                                     language=self.cfg['presidio'].get('idioma', 'pt'))
        for r in res:
            cat = self._MAP.get(r.entity_type.upper())
            if cat:
                ent[cat].append(texto[r.start:r.end])
        return ent


# ---------------------------------------------------------------------------
# Compostos: UNIÃO e ENCADEADO
# ---------------------------------------------------------------------------
def _unir(a, b):
    out = _vazio()
    for k in out:
        vistos, lst = set(), []
        for x in a.get(k, []) + b.get(k, []):
            nx = normalizar(x)
            if nx and nx not in vistos:
                vistos.add(nx)
                lst.append(x)
        out[k] = lst
    return out


class MotorHibridoUniao(MotorEstagio2):
    """União dos conjuntos de dois motores (recomendação de produção)."""

    def __init__(self, motor_a, motor_b):
        self.a, self.b = motor_a, motor_b
        self.nome = f'hibrido({motor_a.nome}∪{motor_b.nome})'
        self.ultimo_prompt_tokens = 0
        self.ultimo_completion_tokens = 0

    def _extrair_bruto(self, texto):
        return _unir(self.a.extrair(texto), self.b.extrair(texto))

    def extrair(self, texto):
        if not texto or not str(texto).strip():
            return _vazio()
        out = self._extrair_bruto(str(texto))   # sub-motores já filtram
        self.ultimo_prompt_tokens = self.a.ultimo_prompt_tokens + self.b.ultimo_prompt_tokens
        self.ultimo_completion_tokens = self.a.ultimo_completion_tokens + self.b.ultimo_completion_tokens
        return out


class MotorEncadeado(MotorEstagio2):
    """Aplica motor_a, substitui, e roda motor_b sobre o texto parcial.

    Mede se a ORDEM degrada o contexto (regex→NER→LLM vs regex→LLM→NER).
    """

    def __init__(self, motor_a, motor_b, ordem='ner_llm'):
        self.a, self.b, self.ordem = motor_a, motor_b, ordem
        self.nome = f'encadeado({motor_a.nome}->{motor_b.nome})'
        self.ultimo_prompt_tokens = 0
        self.ultimo_completion_tokens = 0

    def _extrair_bruto(self, texto):
        e1 = self.a.extrair(texto)
        parcial, _ = aplicar_substituicoes(texto, e1, numerar=False)
        e2 = self.b.extrair(parcial)
        return _unir(e1, e2)

    def extrair(self, texto):
        if not texto or not str(texto).strip():
            return _vazio()
        out = self._extrair_bruto(str(texto))
        self.ultimo_prompt_tokens = self.a.ultimo_prompt_tokens + self.b.ultimo_prompt_tokens
        self.ultimo_completion_tokens = self.a.ultimo_completion_tokens + self.b.ultimo_completion_tokens
        return out


# =============================================================================
# FACTORY
# =============================================================================
def criar_motor(cfg, motor='regex_only', modelo=None, ordem='ner_llm',
                ner_backend='spacy'):
    """Cria um motor do Estágio 2 a partir de config + seleção de CLI.

    motor: regex_only | ner | llm | hibrido | encadeado | presidio
    modelo: nome do modelo NER/LLM (para ner/llm)
    ner_backend: 'spacy' | 'bertimbau' (quando motor envolve NER)
    """
    if motor == 'regex_only':
        return MotorRegexOnly()
    if motor == 'ner':
        return MotorNER(cfg, backend=ner_backend, modelo=modelo)
    if motor == 'llm':
        return MotorLLM(cfg, modelo=modelo)
    if motor == 'presidio':
        return MotorPresidio(cfg)
    if motor in ('hibrido', 'encadeado'):
        # melhor NER + melhor LLM (configurável); padrão: spaCy + 1º LLM
        ner = MotorNER(cfg, backend=ner_backend)
        llm = MotorLLM(cfg, modelo=modelo)
        if motor == 'hibrido':
            return MotorHibridoUniao(ner, llm)
        a, b = (ner, llm) if ordem == 'ner_llm' else (llm, ner)
        return MotorEncadeado(a, b, ordem=ordem)
    raise ValueError(f'motor desconhecido: {motor}')


if __name__ == '__main__':
    # Smoke test (sem modelos): regex_only + filtro + substituição
    ex = ("Esdras Alves Da Silva, vulgo Tubarão, e o autor 2 roubaram a vítima "
          "Maria Regina na Vila Mariana, em frente ao Mercado São Jorge. "
          "A guarnição da viatura prendeu o indivíduo. iPhone subtraído.")
    m = MotorRegexOnly()
    print('regex_only extrai:', m.extrair(ex))
    print('tokens regex_only:', m.ultimo_prompt_tokens, m.ultimo_completion_tokens)
    bruto = {'nomes': ['Esdras Alves Da Silva', 'Maria Regina', 'autor 2',
                       'indivíduo', 'vítima'],
             'locais': ['Vila Mariana', 'esquina'],
             'estabelecimentos': ['Mercado São Jorge', 'mercado'],
             'vulgos': ['Tubarão']}
    filt, n = filtrar_entidades(bruto)
    print('filtrado:', filt, '| removidos:', n)
    out, ns = aplicar_substituicoes(ex, filt)
    print('substituido:', out)
    print('chunks de texto longo:', len(_chunk_para_ner('Frase. ' * 200)))
