# Project Handover & Technical Reference — DVSA Hybrid Booking Bot

## 1. Project Locations & Repository
- **Primary Git Repository**: `C:\Users\zorig\dvsa-booking-bot`
- **GitHub Remote**: `https://github.com/haytim/dvsa-booking-bot.git` (branch: `main`)
- **Scratch Mirror**: `C:\Users\zorig\.gemini\antigravity\scratch\booking-bot`

---

## 2. Architecture & Current State
The bot connects to a running Chrome instance on a secondary monitor via the **Chrome DevTools Protocol (CDP)** (`http://127.0.0.1:9222`, started via `start_chrome.bat`).

### Input Modes (`config.USE_PHYSICAL_MOUSE`)
- **`USE_PHYSICAL_MOUSE = False` (Current Default — 100% Cursor-Free Mode)**:
  - Uses CDP native input (`Input.dispatchMouseEvent` with `mouseMoved`, `mousePressed`, `mouseReleased` and `Input.insertText`) directly inside the Chrome tab viewport (`vx`, `vy`).
  - **Never touches or moves the Windows OS cursor or steals window focus**, allowing uninterrupted work on the primary monitor.
- **`USE_PHYSICAL_MOUSE = True` (PyAutoGUI Fallback)**:
  - Converts DOM `getBoundingClientRect()` coordinates to absolute OS virtual-desktop coordinates (`x`, `y`) accounting for `window.screenX`, `window.screenY`, Chrome's top toolbar border, and browser zoom (`window.devicePixelRatio`, verified working at `0.75` / 75% zoom on Monitor 2).

---

## 3. Workflow & Target Criteria (`config.py`)
1. **Postcode Cycling (`SEARCH_QUERIES`)**:
   - Cycles between `"DD1 4NN"` (returns **Dundee**) and `"EH16 6BG"` (returns **Edinburgh (Musselburgh)** and **Livingston**).
   - Types into `#test-centres-input` and clicks `#test-centres-submit` (`Find test centres`).
2. **Target Test Centres (`TARGET_LOCATIONS`)**:
   - `Dundee`
   - `Edinburgh (Musselburgh)`
   - `Livingston`
3. **Date Matching (`DATE_REGEX` & `evaluate_date_action`)**:
   - Scans `a.test-centre-details-link` banners for `available tests around DD/MM/YYYY`.
   - Note: The dash character before `available tests around` on the page is sometimes encoded as `\ufffd` (Unicode replacement character ``) or an en-dash `–`, so `DATE_REGEX` matches `avai?li?able\s+tests\s+around\s+(\d{2})/(\d{2})/(\d{4})` without requiring a specific dash character.
   - **Auto-Book (`AUTO_BOOK_MONTHS = [(11, 2026), (12, 2026)]`)**:
     - Plays an urgent 4-beep alert (`notify_audible(urgent=True)`).
     - Clicks the matching test centre's green banner (`div.test-centre-details` inside `a.test-centre-details-link`).
   - **Audible Alert Only (`NOTIFY_ONLY_MONTHS = [(1, 2027)]`)**:
     - Plays a 2-tone chime (`notify_audible(urgent=False)`) without clicking away.
   - **Testing Override (`ACCEPT_ANY_DATE_LOCATIONS`)**:
     - Currently `[]`. Set to `["Dundee"]` to immediately test the full booking flow on any available Dundee date regardless of month/year.
4. **Step 5 (`Test time`) Calendar & Slot Selection (`handle_calendar_and_slot_flow`)**:
   - **Step 3.1 (`select_earliest_calendar_date`)**: Polls up to 15s (`ELEMENT_WAIT_TIMEOUT`) for visible bookable calendar cells (`td.BookingCalendar-date--bookable a.BookingCalendar-dateLink` with `rect.width > 0 && rect.height > 0`), sorts chronologically by `data-date="YYYY-MM-DD"`, and clicks the earliest date.
   - **Step 3.2 (`select_latest_time_slot`)**: Scrolls down to the active day's time slots (`.SlotPicker-day.is-active label.SlotPicker-slot-label`), parses `am`/`pm` times into 24-hour minutes, and clicks the latest time slot on that day.
   - **Step 3.3 (`click_continue_button` #1)**: Scrolls to and clicks `#slot-chosen-submit` (`Continue >`).
   - **Step 3.4 (`click_continue_button` #2)**: Waits for the 15-minute slot hold confirmation modal and clicks `#slot-warning-continue` (`Continue`).
   - Stops once it reaches Step 6 (`Your details` / next form page).

---

## 4. Rate Limiting, Captcha & Session Protections
1. **DVSA Hourly Search Limit (~40 searches / 50 step transitions per hour)**:
   - Discovered empirically: starting at `execution=e1s8`, the `"Search limit reached: You've reached the maximum number of searches per hour"` modal (`section.dialog`, `#dialog-label`, dismiss button `a#warning-ok`) triggers on the **40th postcode search** (`execution=e1s58`).
   - **Smart Pacer (`compute_smart_poll_delay`)**: Paces searches at `MAX_SEARCHES_PER_HOUR = 36` (~1 search every `100s ± 8s` jitter) using a rolling 60-minute timestamp deque (`SEARCH_TIMESTAMPS`). This provides 18 checks of Dundee and 18 checks of Edinburgh/Livingston per hour while keeping a 4–14 request reserve to complete the booking when a slot drops.
   - **Modal Recovery (`handle_search_limit_if_present`)**: If `a#warning-ok` appears, clicks `Ok` to dismiss the modal and cools down for 15 minutes (`SEARCH_LIMIT_COOLDOWN_SECONDS = 900`).
2. **Imperva / hCaptcha Security Check Pause (`wait_for_security_check_resolution`)**:
   - Detects `#main-iframe`, `iframe[src*="_Incapsula_Resource"]`, `iframe[src*="hcaptcha"]`, or `"Additional security check is required"` text.
   - Immediately pauses all bot actions, plays a 3-part two-tone alarm (`notify_captcha_alert`), and waits for the user to manually tick *"I am human"*. Automatically resumes 2 seconds after the normal booking DOM reloads.
3. **Session Keep-Alive (`smart_sleep_with_keepalive`)**:
   - During the ~100s polling wait and 15-minute cooldowns, checks every 5 seconds for any session-timeout modal (*"Keep me signed in"* / *"Extend"*) and clicks it automatically.

---

## 5. Planned Next Steps (When Resuming)
1. **Step 6 (`Your details` / Candidate Form Automation)**:
   - Currently, the bot stops right after clicking the second `Continue` button on Step 5 (`[SUCCESS] Reached the next form page! Stopping bot for manual handling.`).
   - Once a screenshot or HTML sample of the next form page (Step 6 `Your details` / Step 7 `Confirm & pay`) is provided, add a handler function after `handle_calendar_and_slot_flow()` to automatically fill or confirm the candidate details form.
2. **Optional Single-Search Optimization**:
   - Check whether searching a midpoint postcode (e.g., Fife/Kinross) and expanding results can cover all 3 target locations in fewer requests if higher per-location check frequency is ever desired.
3. **Session Expiry Re-Login (Optional)**:
   - If the browser is left idle at a login screen or kicked back to Step 1/2 (`Licence details`), add optional auto-fill for driving licence number + booking reference to return to Step 4 (`Test centre`) automatically.
