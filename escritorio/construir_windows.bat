@echo off
REM Genera dist\BI_Suicidio\ con el .exe portable y config.json, lista para copiar a la memoria USB.
cd /d %~dp0
python -m venv .venv-build || goto :error
call .venv-build\Scripts\activate.bat
pip install -r requirements.txt || goto :error
pyinstaller --noconfirm --onefile --windowed --name BI_Suicidio --distpath dist\BI_Suicidio app.py || goto :error
copy /Y config.json dist\BI_Suicidio\config.json
copy /Y LEEME.txt dist\BI_Suicidio\LEEME.txt
echo.
echo Listo: copie la carpeta dist\BI_Suicidio a la memoria USB.
exit /b 0
:error
echo Fallo la construccion.
exit /b 1
