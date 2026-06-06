#!/usr/bin/env bash
cd "$(dirname "$0")"
python -m pip install -r requirements.txt
python -m spacy download pt_core_news_lg || true
streamlit run app.py
