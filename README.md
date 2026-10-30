# DVSA Hybrid Booking Bot (Chrome CDP + PyAutoGUI)

A hybrid automation bot that monitors test centres on a secondary monitor using a live Chrome instance (`--remote-debugging-port=9222`) to read DOM coordinates and `pyautogui` to perform physical mouse movements, scrolling, and clicks.

## Features
- **Postcode Cycling**: Automatically cycles through configured postcodes (`DD1 4NN`, `EH16 6BG`) and clicks **Find test centres**.
- **Smart Date Filtering**:
  - **Auto-Book (`11/2026`, `12/2026`)**: Plays an urgent alert, clicks the test centre banner (`Dundee`, `Edinburgh (Musselburgh)`, `Livingston`), selects the earliest available date on the calendar, scrolls to select the latest time slot on that day, and clicks **Continue** twice.
  - **Notify Only (`01/2027`)**: Plays an audible notification chime without leaving the search loop.
- **Multi-Monitor & Zoom Aware**: Calculates exact OS screen `(x, y)` coordinates across monitors and browser zoom levels.

## Setup

1. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

2. Launch Chrome with Remote Debugging enabled:
   ```powershell
   .\start_chrome.bat
   ```
   Move the opened Chrome window to your second monitor and navigate to the **Test centre** search page.

3. Run the bot:
   ```powershell
   python bot.py
   ```

   To test only the calendar/slot/continue flow on an already-open **Test time** calendar page:
   ```powershell
   python bot.py --test-calendar
   ```

> **Fail-safe**: Move your mouse cursor rapidly to any corner of your primary monitor to abort `pyautogui` at any time.

