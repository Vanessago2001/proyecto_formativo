@echo off
REM Arranca CertiSENA con el entorno virtual del proyecto.
REM Se puede ejecutar con doble clic, o desde la consola pasando opciones:
REM     iniciar.bat --preparar     prepara la base (la primera vez)
REM     iniciar.bat --recargar     reinicia al guardar un archivo

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo No se encontro el entorno virtual en venv\
    echo Cree uno con:  python -m venv venv
    pause
    exit /b 1
)

"venv\Scripts\python.exe" iniciar.py %*

if errorlevel 1 pause
