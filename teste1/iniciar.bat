@echo off
echo Abrindo 5gbet com DevTools...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --auto-open-devtools-for-tabs "https://www.5gbet.com"
timeout /t 5 /nobreak
echo Iniciando bot...
cd C:\Users\tuex7\Desktop\teste1
C:\Users\tuex7\AppData\Local\Programs\Python\Python314\python.exe bacbo_completo.py
pause