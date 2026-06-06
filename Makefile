.PHONY: reproduce figure app api clean

reproduce:        ## Reproduz tabelas, ICs e figura (sem Ollama)
	python -m pip install -r requirements.txt
	python metricas_utilidade.py
	python analise_estatistica.py
	python figura_tradeoff.py

figure:           ## Regenera apenas a figura do trade-off
	python figura_tradeoff.py

app:              ## Inicia a interface web (Streamlit)
	cd app && streamlit run app.py

api:              ## Inicia a API REST (FastAPI/uvicorn) em 127.0.0.1:8000
	cd app && uvicorn api:app --host 127.0.0.1 --port 8000

clean:            ## Remove caches e artefatos temporarios
	rm -rf __pycache__ fig_tradeoff.pdf
