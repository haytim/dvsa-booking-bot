# Hybrid Browser UI Automation Case Study (Chrome CDP + PyAutoGUI)

> ### ⚠️ Educational & Technical Research Disclaimer
>
> **This repository is an archived software engineering proof-of-concept and technical research case study.** It is published strictly for **educational, academic, and portfolio demonstration purposes** to illustrate hybrid browser automation architectures (Chrome DevTools Protocol viewport coordinate projection vs. OS-level virtual desktop input dispatch) and DOM workflow testing.
>
> - **Not Intended for Live Use**: Automated scraping, polling, or booking on live Driver and Vehicle Standards Agency (DVSA) systems is prohibited by the **DVSA Terms and Conditions and Acceptable Use Policy**. This codebase is **not** intended or distributed for individuals to run against live DVSA infrastructure.
> - **No Security Bypass**: This software explicitly **does not** bypass, defeat, or automate CAPTCHA challenges or security access controls; execution halts immediately if a security challenge is present.
> - **Safe Defaults (`DRY_RUN = True`)**: Out of the box, `DRY_RUN = True` is enabled in [`config.py`](./config.py) so that live booking transitions and form submissions are disabled by default.
> - **No Liability**: Provided "AS IS" under the [MIT License](./LICENSE) for technical study only. The author(s) do not endorse, encourage, or assume liability for any third-party misuse.

---

## Technical Overview

This project explores two complementary approaches to driving UI workflows inside a standard Chromium browser instance via the **Chrome DevTools Protocol (CDP)** (`--remote-debugging-port=9222`):

1. **Cursor-Free CDP Viewport Dispatch (`USE_PHYSICAL_MOUSE = False`, default)**:
   - Evaluates live DOM bounding boxes (`Element.getBoundingClientRect()`) and dispatches native viewport events (`Input.dispatchMouseEvent`, `Input.insertText`) directly to the target renderer tab without moving the host OS cursor or stealing window focus.
2. **Multi-Monitor & DPI-Aware Physical Input (`USE_PHYSICAL_MOUSE = True`)**:
   - Projects DOM viewport coordinates `(vx, vy)` into absolute OS virtual-desktop coordinates `(x, y)` accounting for `window.screenX`, `window.screenY`, browser chrome/toolbar offsets, and `window.devicePixelRatio` zoom scaling via `PyAutoGUI`.

---

## Configuration & What Needs to Be Modified

To configure the project for a test environment or local snapshot workflow, two files control all runtime parameters and form data:

### 1. Candidate Details (`candidate_details.py`)
Step 6 (`Your details`) reads candidate form fields from `candidate_details.py` (which is ignored by `.gitignore` so personal data is never committed).

1. Copy [`candidate_details.example.py`](./candidate_details.example.py) to `candidate_details.py`:
   ```powershell
   Copy-Item candidate_details.example.py candidate_details.py
   ```
2. Populate the dictionary fields in `candidate_details.py`:
   ```python
   CANDIDATE_DETAILS = {
       "title": "Mr",                  # Dropdown option: "Mr", "Mrs", "Miss", "Ms", "Dr", "Mx", etc.
       "first_names": "John",
       "surname": "Doe",
       "address_line_1": "10 Example Street",
       "address_line_2": "",           # Optional second address line
       "town": "Edinburgh",
       "postcode": "EH14 4AS",
       "email": "john.doe@example.com",
       "confirm_email": "john.doe@example.com",
       "contact_number": "07700900000",
   }
   ```

### 2. Search, Target & Pacing Parameters ([`config.py`](./config.py))
Open [`config.py`](./config.py) and configure the following settings:

| Setting | Default in Repo | What to Modify |
| :--- | :--- | :--- |
| `DRY_RUN` | `True` | Set to `False` to enable clicking through matching test centres and submitting Step 6 (`Your details`). When `True`, matches are logged only. |
| `SEARCH_QUERIES` | `["EH14 4AS"]` | List of postcodes or test centre query strings to cycle through in `#test-centres-input` (e.g. `["EH14 4AS", "EH16 6BG"]`). Leave `[]` to re-submit whatever is already in the search box. |
| `TARGET_LOCATIONS` | `["Edinburgh (Currie)"]` | Exact test centre heading names to scan under *"Your search results"* (e.g. `["Edinburgh (Currie)", "Edinburgh (Musselburgh)", "Livingston"]`). |
| `AUTO_BOOK_MONTHS` | `[]` | List of `(month, year)` tuples that trigger the automated calendar/slot/form flow, e.g. `[(11, 2026), (12, 2026)]`. |
| `NOTIFY_ONLY_MONTHS` | `[]` | List of `(month, year)` tuples that play a two-tone audible chime without leaving the search results page, e.g. `[(1, 2027)]`. |
| `ACCEPT_ANY_DATE_LOCATIONS` | `[]` | Optional override list of location names (e.g. `["Edinburgh (Currie)"]`) to trigger the booking flow on *any* available date regardless of month/year (useful for testing). |
| `MAX_SEARCHES_PER_HOUR` | `36` | Target searches per rolling 60-minute window (`36` = ~1 search every 100s, keeping below the ~40 searches/hour session limit). |
| `USE_PHYSICAL_MOUSE` | `False` | `False` uses 100% cursor-free CDP viewport events. Set to `True` to use physical OS mouse movement via `PyAutoGUI`. |

---

## Setup & Running

1. **Install Python dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

2. **Start the script (auto-launches Chrome on port `9222`)**:
   ```powershell
   python bot.py
   ```
   - If Chrome is not already running on `http://127.0.0.1:9222`, `bot.py` automatically runs [`start_chrome.bat`](./start_chrome.bat) using an isolated profile (`%LOCALAPPDATA%\Google\Chrome\BotProfile`).
   - Navigate to the **Test centre** search step in the opened Chrome window; `bot.py` detects when the page is loaded and starts monitoring automatically.

3. **Individual Step / Offline Snapshot Test Modes**:
   You can test the calendar selection or candidate form auto-fill directly against an open page or saved local `.html` snapshot:
   ```powershell
   # Test Step 5 (earliest calendar date + latest time slot + Continue) on the open tab:
   python bot.py --test-calendar

   # Test Step 6 ('Your details' form auto-fill) without clicking the final submit button:
   python bot.py --test-details --no-submit

   # Test Step 6 ('Your details' form auto-fill) including the 'Next: payment details' button:
   python bot.py --test-details
   ```

> **PyAutoGUI Fail-Safe**: When `USE_PHYSICAL_MOUSE = True`, moving the OS cursor rapidly to any corner of your primary monitor triggers `pyautogui.FAILSAFE` and aborts execution immediately.
