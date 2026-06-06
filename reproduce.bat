@echo off
REM Reproduz, sem Ollama, as tabelas/ICs/figura do artigo a partir das saidas congeladas.
cd /d %~dp0
python -m pip install -r requirements.txt || goto err
python metricas_utilidade.py || goto err
python analise_estatistica.py || goto err
python figura_tradeoff.py || goto err
echo OK: veja results\ e fig_tradeoff.pdf
goto :eof
:err
echo Falha na reproducao.
exit /b 1
