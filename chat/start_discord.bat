@echo off
cd /d C:\Users\Nexus\Nexus
:loop
"C:\Users\Nexus\AppData\Local\Programs\Python\Python312\python.exe" chat\discord_bot.py >> logs\discord.log 2>&1
timeout /t 5 /nobreak
goto loop
