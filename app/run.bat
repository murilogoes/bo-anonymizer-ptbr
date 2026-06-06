@echo off
cd /d %~dp0
python -m pip install -r requirements.txt
python -m spacy download pt_core_news_lg
streamlit run app.py
