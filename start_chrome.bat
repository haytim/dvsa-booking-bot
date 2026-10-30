@echo off
REM Launches Chrome with Remote Debugging enabled on port 9222 using a dedicated profile
REM Move this Chrome window to your second monitor and navigate to the booking page.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\BotProfile"

