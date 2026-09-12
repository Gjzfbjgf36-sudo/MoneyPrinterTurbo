@echo off
rem Doppelklick-Start der WebUI.
rem
rem Im Gegensatz zu webui.bat, das sich auf das aktuelle Verzeichnis (%CD%)
rem verlaesst, wechselt diese Datei zuerst in ihren eigenen Ordner (%~dp0).
rem Das ist der Unterschied, der aus einer Desktop-Verknuepfung oder aus einem
rem geplanten Task heraus zaehlt: dort ist das aktuelle Verzeichnis oft
rem C:\Windows\system32, und webui.bat wuerde dann die Projektdateien nicht
rem finden.
setlocal
cd /d "%~dp0"

echo ===============================================
echo  MoneyPrinterTurbo wird gestartet
echo  Der Browser oeffnet sich gleich von selbst.
echo.
echo  Dieses Fenster bitte offen lassen.
echo  Zum Beenden: Strg+C oder Fenster schliessen.
echo ===============================================
echo.

rem uv liegt nicht immer im PATH, etwa direkt nach der Installation oder in
rem einem geplanten Task. Deshalb den Standardpfad zusaetzlich anbieten.
if not defined UV_BIN set "UV_BIN=%USERPROFILE%\.local\bin\uv.exe"
if exist "%UV_BIN%" set "PATH=%USERPROFILE%\.local\bin;%PATH%"

call "%~dp0webui.bat"

rem Faellt die WebUI mit einem Fehler aus, wuerde das Fenster sofort
rem verschwinden und die Meldung mitnehmen.
if errorlevel 1 (
    echo.
    echo ***** Die WebUI wurde mit einem Fehler beendet. *****
    echo ***** Meldung oben lesen, dann Taste druecken.  *****
    pause
)
endlocal
