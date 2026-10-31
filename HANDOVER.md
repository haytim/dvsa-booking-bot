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
5. **Step 6 (`Your details`) Candidate Form Automation (`fill_candidate_details_and_submit`)**:
   - Reads private candidate details from `candidate_details.py` (git-ignored via `.gitignore`).
   - Selects **Title** (`#details-suffix` / `select[name="title"]` -> `"Mr"`) and fills `#details-first-names`, `#details-surname`, `#details-address-1`, `#details-town`, `#details-postcode`, `#details-email`, `#details-confirm-email`, and `#details-contact-number`.
   - Clicks `#details-submit` (`Next: payment details`), reaching Step 7 (`Card details`) with the 15-minute slot hold active, and plays an urgent chime.
   - Can be tested directly at any time via `python bot.py --test-details` (or `python bot.py --test-details --no-submit`).

---

## 4. Rate Limiting, Captcha & Session Protections
1. **DVSA Hourly Search Limit & Empirical Telemetry (`MAX_SEARCHES_PER_HOUR = 72`)**:
   - Currently configured at `MAX_SEARCHES_PER_HOUR = 72` (~1 search every `50s ± 5s` jitter) to push the rate limit and empirically track when failures occur.
   - **Empirical Limit & Failure Detector (`handle_search_limit_if_present`, `log_telemetry_event`)**:
     - Tracks every search in a rolling 60-minute window (`SEARCH_TIMESTAMPS`), total session searches (`TOTAL_SUCCESSFUL_SEARCHES`), searches since the last limit (`SEARCHES_SINCE_LAST_LIMIT`), and the exact Spring Web Flow state counter (`execution=e1s<N>` via `get_execution_step`).
     - When `"Search limit reached"` (`a#warning-ok`) or an Imperva security check triggers, it calculates the exact **Empirical Max Searches (last 60m)**, elapsed window time, effective hourly pace, `e1sXX` transition delta, and recommended safe limit (`discovered_max - 4`), printing a summary report and appending a structured event to `search_limit_log.jsonl`.
     - **Modal Recovery & Recovery Probing**: Dismisses `a#warning-ok`, pauses for `SEARCH_LIMIT_COOLDOWN_SECONDS = 300` (5 minutes), and logs a `"search_limit_recovered"` event with the exact recovery duration once the next search succeeds.
     - Optional `AUTO_ADAPT_PACE_ON_LIMIT` (default `False` in `config.py`): if set to `True`, automatically throttles `EFFECTIVE_MAX_SEARCHES_PER_HOUR` to the discovered safe limit after hitting the cap.
2. **Midpoint Postcode Findings (Verified Live)**:
   - Each initial DVSA postcode search returns **4 test centres**, and each click of `"Show more results"` (`#fetch-more-centres`, `_eventId=loadMore`) adds 4 more centres while consuming 1 `execution=e1sXX` state transition.
   - Because **Kirkcaldy**, **Dunfermline (Vine)**, and **Edinburgh (Currie)** sit geographically inside the triangle between **Dundee**, **Edinburgh (Musselburgh)**, and **Livingston**, no single initial 4-result search can return all 3 target centres (`KY1 1PA` requires 2 clicks of `"Show more results"` = 3 transitions to reach 12 centres including Dundee).
   - Cycling `"DD1 4NN"` (1 request -> Dundee) and `"EH16 6BG"` (1 request -> Musselburgh + Livingston) is therefore already the theoretical minimum (**2 requests** to check all 3 centres).
3. **Imperva Error 15 (`Access Denied`) vs Interactive Captcha (`is_error_15_block_page` & `wait_for_error_15_resolution`)**:
   - **Imperva Error 15 (`Access Denied — You have been blocked by DVSA security rules`)**:
     - Inspected inside both `document.body` and `#main-iframe` (`contentDocument.body.innerText`). Triggered at ~49 transitions (`execution=e2s49`) when pushing 72 searches/hr.
     - Handled automatically without captcha beeping via cumulative retry milestones `ERROR_15_RETRY_MINUTES = [15, 30, 60]`: waits **15 minutes**, reloads the page (`window.location.reload()`), if still blocked waits until **30 minutes**, reloads, and if still blocked waits until **60 minutes** (then every 15m thereafter). Logs `"error_15_temporary_block"` and `"error_15_recovered"` to `search_limit_log.jsonl`.
   - **Interactive Captcha (`is_security_check_page` / `wait_for_security_check_resolution`)**:
     - Detects hCaptcha / `"Additional security check is required"` when it is *not* Error 15.
     - Plays the two-tone alert **once** (`notify_captcha_alert`), waits for the user to tick *"I am human"*, and exits cleanly if the Chrome tab is closed.
4. **Session Keep-Alive (`smart_sleep_with_keepalive`)**:
   - During polling waits and cooldowns, checks every 5 seconds for any session-timeout modal (*"Keep me signed in"* / *"Extend"*) and clicks it automatically.

---

## 5. Planned Next Steps (When Resuming)
1. **Step 6 (`Your details` / Candidate Form Automation)**:
   - Currently, the bot stops right after clicking the second `Continue` button on Step 5 (`[SUCCESS] Reached the next form page! Stopping bot for manual handling.`).
   - Once a screenshot or HTML sample of the next form page (Step 6 `Your details` / Step 7 `Confirm & pay`) is provided, add a handler function after `handle_calendar_and_slot_flow()` to automatically fill or confirm the candidate details form.
2. **Session Expiry Re-Login (Optional)**:
   - If the browser is left idle at a login screen or kicked back to Step 1/2 (`Licence details`), add optional auto-fill for driving licence number + booking reference to return to Step 4 (`Test centre`) automatically.

