# -*- coding: utf-8 -*-
"""Anonimizador de Históricos de BO — aplicativo local (Streamlit) com login.

Executa 100% na máquina do usuário. Nenhum dado é enviado para a internet.
Rodar:  streamlit run app.py
"""
import io
import re
import pandas as pd
import streamlit as st

import anonimizador_core as core
import auth

auth.init_db()
st.set_page_config(page_title="Anonimizador de Históricos de BO", page_icon="🛡️", layout="wide")

if "user" not in st.session_state:
    st.session_state.user = None

st.title("🛡️ Anonimizador de Históricos de Boletim de Ocorrência")
st.success("🔒 **Processamento 100% local.** Seus dados não saem desta máquina.")

# ============================================================ AUTENTICAÇÃO
def tela_login():
    if auth.contar_usuarios() == 0:
        st.subheader("Configuração inicial — criar o primeiro administrador")
        st.info("Nenhum usuário cadastrado. Crie o administrador inicial.")
        with st.form("setup"):
            u = st.text_input("Usuário")
            p1 = st.text_input("Senha", type="password")
            p2 = st.text_input("Repita a senha", type="password")
            if st.form_submit_button("Criar administrador", type="primary"):
                if p1 != p2:
                    st.error("As senhas não coincidem.")
                else:
                    try:
                        auth.criar_usuario(u, p1, "admin")
                        st.success("Administrador criado. Faça login.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
    else:
        st.subheader("Entrar")
        with st.form("login"):
            u = st.text_input("Usuário")
            p = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar", type="primary"):
                user = auth.verificar_login(u, p)
                if user:
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("Usuário ou senha inválidos.")
    st.stop()

if not st.session_state.user:
    tela_login()

user = st.session_state.user

# ============================================================ APP (logado)
status = core.checar_ambiente()
disp = dict(core.presets_disponiveis(status))

with st.sidebar:
    st.write(f"👤 **{user['username']}** ({user['role']})")
    if st.button("Sair"):
        st.session_state.user = None
        st.rerun()
    st.divider()
    st.header("Configuração")
    opcoes = [n for n, ok in disp.items() if ok] or list(core.PRESETS.keys())
    preset = st.selectbox("Pipeline (preset)", opcoes,
                          help="Recomendado = melhor equilíbrio; Máxima segurança = menor "
                               "vazamento; Leve/offline = sem LLM, roda em qualquer máquina.")
    st.markdown("**Ambiente detectado:**")
    st.write(("✅" if status["ollama"] else "⚠️") + " Ollama (LLM local)")
    st.write(("✅" if status["spacy"] else "⚠️") + f" spaCy ({status['spacy_model']})")

st.caption("Anonimização **supervisionada**: revise o resíduo (~1,4% das entidades) antes de "
           "publicar. Reduz o risco de exposição de PII, mas não garante conformidade automática "
           "com a LGPD.")

def realcar(texto):
    return re.sub(r"(\[[A-Z_]+\d*\])", r":red-background[**\1**]", texto)

abas = ["📝 Texto único", "📄 Planilha (lote)"]
if user["role"] == "admin":
    abas.append("⚙️ Administração")
tabs = st.tabs(abas)

# ---------------------------------------------------------- texto único
with tabs[0]:
    st.subheader("Anonimizar um texto")
    exemplo = ("Comparece nesta delegacia a vítima João da Silva, RG 12.345.678-9, "
               "telefone (11) 98765-4321, relatando roubo na Rua das Flores, 100, "
               "Jardim Primavera, por um indivíduo conhecido como Zé.")
    txt = st.text_area("Cole aqui o texto do histórico:", value=exemplo, height=160)
    if st.button("Anonimizar texto", type="primary"):
        with st.spinner("Anonimizando localmente…"):
            try:
                saida = core.anonimizar_texto(txt, preset)
                c1, c2 = st.columns(2)
                c1.markdown("**Entrada**"); c1.write(txt)
                c2.markdown("**Saída anonimizada**"); c2.markdown(realcar(saida))
            except Exception as e:
                st.error(f"Falha ao anonimizar: {e}")

# ---------------------------------------------------------- lote
with tabs[1]:
    st.subheader("Anonimizar uma planilha (.xlsx)")
    up = st.file_uploader("Envie a planilha Excel", type=["xlsx", "xls"])
    if up is not None:
        try:
            df = pd.read_excel(up)
        except Exception as e:
            st.error(f"Não foi possível ler a planilha: {e}"); df = None
        if df is not None:
            st.write(f"Linhas: {len(df)} · Colunas: {list(df.columns)}")
            coluna = st.selectbox("Qual coluna contém o texto a anonimizar?", list(df.columns))
            st.dataframe(df.head(5), use_container_width=True)
            if st.button("Anonimizar planilha", type="primary"):
                barra = st.progress(0.0, text="Processando localmente…")
                try:
                    saidas = core.anonimizar_serie(
                        df[coluna].fillna("").astype(str).tolist(), preset,
                        progresso=lambda f: barra.progress(f, text=f"Processando… {int(f*100)}%"))
                    nova = df.copy(); nova[f"{coluna} [anonimizado]"] = saidas
                    barra.progress(1.0, text="Concluído.")
                    st.success("Concluído. Revise o resíduo antes de publicar.")
                    st.dataframe(nova.head(10), use_container_width=True)
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="openpyxl") as w:
                        nova.to_excel(w, index=False)
                    st.download_button("⬇️ Baixar planilha anonimizada", buf.getvalue(),
                        file_name="planilha_anonimizada.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                except Exception as e:
                    st.error(f"Falha ao processar: {e}")

# ---------------------------------------------------------- administração
if user["role"] == "admin":
    with tabs[2]:
        st.subheader("Gestão de usuários")
        with st.expander("➕ Cadastrar novo usuário", expanded=False):
            with st.form("novo_user"):
                nu = st.text_input("Usuário")
                np_ = st.text_input("Senha", type="password")
                nr = st.selectbox("Perfil", ["comum", "admin"])
                if st.form_submit_button("Criar"):
                    try:
                        auth.criar_usuario(nu, np_, nr); st.success("Usuário criado."); st.rerun()
                    except ValueError as e:
                        st.error(str(e))
        st.dataframe(pd.DataFrame(auth.listar_usuarios()), use_container_width=True)
        usuarios = [u["username"] for u in auth.listar_usuarios()]
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Redefinir senha / perfil**")
            alvo = st.selectbox("Usuário", usuarios, key="alvo_edit")
            ns = st.text_input("Nova senha (opcional)", type="password", key="ns")
            npf = st.selectbox("Novo perfil (opcional)", ["(manter)", "comum", "admin"], key="npf")
            if st.button("Aplicar alterações"):
                try:
                    if ns: auth.alterar_senha(alvo, ns)
                    if npf != "(manter)": auth.alterar_papel(alvo, npf)
                    st.success("Atualizado."); st.rerun()
                except ValueError as e:
                    st.error(str(e))
        with col2:
            st.markdown("**Remover usuário**")
            alvo_rm = st.selectbox("Usuário", usuarios, key="alvo_rm")
            if st.button("Remover", type="secondary"):
                try:
                    auth.remover_usuario(alvo_rm); st.success("Removido."); st.rerun()
                except ValueError as e:
                    st.error(str(e))

        st.divider()
        st.subheader("Chaves de API")
        st.caption("Use a chave no cabeçalho `Authorization: Bearer <chave>` ao chamar a API REST.")
        with st.form("nova_key"):
            lbl = st.text_input("Rótulo da chave (ex.: integração-SSP)")
            if st.form_submit_button("Gerar nova chave"):
                raw = auth.gerar_api_key(lbl, user["username"])
                st.warning("Copie agora — esta chave **não** será exibida novamente:")
                st.code(raw, language="text")
        keys = auth.listar_api_keys()
        if keys:
            st.dataframe(pd.DataFrame(keys), use_container_width=True)
            ativos = [k["id"] for k in keys if k["active"] == 1]
            if ativos:
                rid = st.selectbox("Revogar chave (id)", ativos)
                if st.button("Revogar chave"):
                    auth.revogar_api_key(rid); st.success("Chave revogada."); st.rerun()

st.divider()
st.caption("Pipeline e dataset descritos em: *Local Anonymization of Free-Text Robbery "
           "Police Reports in Brazilian Portuguese* (KDMiLe). Código aberto.")
