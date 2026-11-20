# Technical Architecture & Research Notes — Hybrid Browser UI Automation

> **Disclaimer**: This document is a technical reference and software engineering post-mortem for an archived educational research project. Automated interaction with live DVSA services violates DVSA Terms of Use. This code and documentation are provided solely for educational and architectural study and are not intended for use by individuals against live government systems.

---

## 1. Repository Structure
- `bot.py`: Core Chrome DevTools Protocol (CDP) bridge, viewport-to-OS coordinate projection, DOM polling, and offline snapshot test runners (`--test-calendar`, `--test-details`).
- `config.py`: Demonstration configuration (defaults to `DRY_RUN = True`, example postcode `"EH14 4AS"` / `"Edinburgh (Currie)"`).
- `candidate_details.example.py`: Synthetic dummy data template for testing Step 6 (`Your details`) form population against local HTML snapshots.
- `start_chrome.bat`: Launches an isolated Chrome profile with `--remote-debugging-port=9222`.

---

## 2. Input Architecture (`config.USE_PHYSICAL_MOUSE`)
The automation engine connects to a local Chrome instance via the **Chrome DevTools Protocol (CDP)** (`http://127.0.0.1:9222`).

### Input Modes
- **`USE_PHYSICAL_MOUSE = False` (100% Cursor-Free CDP Mode)**:
  - Uses CDP native input (`Input.dispatchMouseEvent` with `mouseMoved`, `mousePressed`, `mouseReleased` and `Input.insertText`) directly inside the Chrome tab viewport `(vx, vy)`.
  - Never touches or moves the Windows OS cursor or steals window focus.
- **`USE_PHYSICAL_MOUSE = True` (OS Coordinate Projection Fallback)**:
  - Converts DOM `getBoundingClientRect()` coordinates to absolute OS virtual-desktop coordinates `(x, y)` accounting for `window.screenX`, `window.screenY`, Chrome's top toolbar border, and browser zoom (`window.devicePixelRatio`).

---

## 3. UI Workflow & DOM Selectors Studied
1. **Search Query Input (`SEARCH_QUERIES`)**:
   - Example configuration uses `"EH14 4AS"` (`Edinburgh (Currie)`).
   - Populates `#test-centres-input` and triggers `#test-centres-submit` (`Find test centres`).
2. **Result Banner Parsing (`DATE_REGEX` & `evaluate_date_action`)**:
   - Scans `a.test-centre-details-link` banners for `available tests around DD/MM/YYYY`.
   - Handles character encoding variations on the separator dash (`\ufffd` or en-dash `–`).
   - When `config.DRY_RUN = True` (the default), matches are logged without clicking through live booking transitions.
3. **Calendar & Slot Selection (`handle_calendar_and_slot_flow`)**:
   - **`select_earliest_calendar_date`**: Queries visible bookable cells (`td.BookingCalendar-date--bookable a.BookingCalendar-dateLink` with `rect.width > 0 && rect.height > 0`), sorts chronologically by `data-date="YYYY-MM-DD"`, and selects the earliest date.
   - **`select_latest_time_slot`**: Scrolls to `.SlotPicker-day.is-active label.SlotPicker-slot-label`, parses `am`/`pm` strings into 24-hour minutes, and selects the latest slot.
   - **`click_continue_button`**: Interacts with `#slot-chosen-submit` (`Continue >`) and `#slot-warning-continue`.
4. **Candidate Form Snapshot Testing (`fill_candidate_details_and_submit`)**:
   - Reads synthetic fields from `candidate_details.py` (or `candidate_details.example.py`).
   - Populates `#details-suffix` (`select[name="title"]`), `#details-first-names`, `#details-surname`, `#details-address-1`, `#details-town`, `#details-postcode`, `#details-email`, `#details-confirm-email`, and `#details-contact-number`, firing standard DOM `input`, `change`, and `blur` events.
   - Can be run offline against a saved HTML file via `python bot.py --test-details --no-submit`.

---

## 4. Rate-Limit & Session Observations
1. **Spring Web Flow State-Transition Ceiling**:
   - Empirical observation shows a session limit of ~40 searches (~50 `execution=e1s<N>` state transitions) per rolling 60-minute window before the `#dialog-label` (`"Search limit reached"`) modal or an Imperva `Error 15` temporary cooldown appears.
   - **`compute_smart_poll_delay`**: Models a rolling 60-minute window (`SEARCH_TIMESTAMPS`) to pace requests below the ceiling.
2. **Security Challenge Respect (`wait_for_security_check_resolution`)**:
   - The script explicitly does **not** bypass or automate CAPTCHA challenges. If an interactive security check is detected, all automated actions halt immediately.
