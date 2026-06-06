# Anonimizador de Históricos de BO (app local)

Aplicativo **100% local** para anonimizar o campo livre "Histórico" de boletins de
ocorrência (BOs), com as melhores pipelines do artigo *Local Anonymization of
Free-Text Robbery Police Reports in Brazilian Portuguese* (KDMiLe).
Inclui **interface web** (com login), **painel de administração** e **API REST**.

> 🔒 **Privacidade.** Todo o processamento ocorre na sua máquina; nenhum dado vai à
> internet. Anonimização **supervisionada**: revise o resíduo (~1,4% das entidades)
> antes de publicar. Não garante conformidade automática com a LGPD.

Esta pasta é **autocontida** — copie-a para a máquina de destino.

## Componentes
- **Interface (Streamlit):** login, anonimização de texto único e de planilhas, e
  painel de administração (apenas para perfil *admin*).
- **API REST (FastAPI):** endpoint autenticado por chave (token) para integração.
- **Banco local (SQLite):** `anonimizador.db` guarda usuários (senha em PBKDF2) e
  os *hashes* das chaves de API. Não é versionado (ver `.gitignore`).

## Presets de pipeline
- **Recomendado (qwen3:8b)** — melhor equilíbrio. *Requer Ollama.*
- **Máxima segurança (união)** — spaCy ∪ qwen3, menor vazamento. *Requer Ollama + spaCy.*
- **Leve/offline (spaCy)** — sem LLM; roda em qualquer máquina. *Requer apenas spaCy.*

## Pré-requisitos
- **Python 3.10+**. Para presets com LLM: **[Ollama](https://ollama.com)** instalado e rodando.

## Instalação
```bash
pip install -r requirements.txt
python -m spacy download pt_core_news_lg
# presets com LLM:
ollama pull qwen3:8b
```

## Interface web (com login)
```bash
streamlit run app.py            # ou: run.bat (Windows) / ./run.sh
```
- No **primeiro acesso**, a tela pede a criação do **administrador inicial**.
- Depois, faça login. O perfil **admin** vê a aba **Administração** para:
  - cadastrar usuários **comuns** e **administradores**;
  - redefinir senha / alterar perfil / remover usuários;
  - **gerar e revogar chaves de API** (a chave é exibida uma única vez).

## API REST
```bash
uvicorn api:app --host 127.0.0.1 --port 8000     # ou: run_api.bat / ./run_api.sh
```
Endpoints:
- `GET /health` → `{"status":"ok"}`
- `POST /anonimizar` (autenticado)
  ```bash
  curl -X POST http://127.0.0.1:8000/anonimizar \
       -H "Authorization: Bearer SUA_CHAVE" \
       -H "Content-Type: application/json" \
       -d '{"texto":"Vítima João da Silva, tel (11) 98765-4321.", "preset":"Leve/offline (spaCy)"}'
  ```
  Resposta: `{"preset":"…","anonimizado":"…"}`. Gere a chave no painel **Administração**.

> A API escuta só em `127.0.0.1` (local). Para expor na rede interna, use um proxy
> com HTTPS e restrinja por firewall — nunca exponha diretamente à internet.

## Conteúdo da pasta
`app.py` (UI) · `api.py` (API) · `auth.py` (SQLite/login/chaves) ·
`anonimizador_core.py` (wrapper da pipeline) · `estagio1_regex.py`, `estagio2_motores.py`
(pipeline) · `config.yaml` · `requirements.txt` · `run*.sh/.bat` · `.gitignore`.
