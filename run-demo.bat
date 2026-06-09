@echo off

pip install -r requirements.txt

if exist support.db del support.db

if exist uploads rd /s /q uploads
mkdir uploads

set ATTACK_USER_EMAIL=mvidaurre@frba.utn.edu.ar
set ATTACK_USER_NAME=Matias Vidaurre2323232

set SMTP_HOST=smtp.gmail.com
set SMTP_PORT=587
set SMTP_USER=matiasvidaurre3a@gmail.com
set SMTP_PASS=mosv wnat wiqx mlvu
set SMTP_FROM=matiasvidaurre3a@gmail.com
python app.py

pause
