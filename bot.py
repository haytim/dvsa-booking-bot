import argparse
import collections
import json
import random
import re
import time
import winsound
from typing import Any, Deque, Dict, List, Optional

import pyautogui
import requests
import websocket

import config

# Enable PyAutoGUI fail-safe (if USE_PHYSICAL_MOUSE is enabled)
pyautogui.FAILSAFE = True

# Rolling 60-minute window of search timestamps
SEARCH_TIMESTAMPS: Deque[float] = collections.deque()


class ChromeCDPBridge:
    """Connects to a running Chrome instance via Chrome DevTools Protocol (CDP)
    to inspect the live DOM and dispatch native browser clicks/typing (or OS coordinates).
    """

    def __init__(self, host: str = config.CDP_HOST):
        self.host = host.rstrip("/")
        self.ws: Optional[websocket.WebSocket] = None
        self._msg_id = 0

    def connect(self, url_keyword: Optional[str] = None) -> None:
        resp = requests.get(f"{self.host}/json", timeout=5)
        resp.raise_for_status()
        targets = resp.json()

        page_target = None
        for t in targets:
            if t.get("type") != "page":
                continue
            if url_keyword and url_keyword.lower() not in t.get("url", "").lower():
                continue
            if not t.get("url", "").startswith("devtools://"):
                page_target = t
                break

        if not page_target:
            raise RuntimeError(
                "No matching Chrome page tab found. Make sure Chrome was started with "
                "--remote-debugging-port=9222 (see start_chrome.bat)."
            )

        ws_url = page_target["webSocketDebuggerUrl"]
        self.ws = websocket.create_connection(ws_url, timeout=10)
        print(f"[CDP] Connected to tab: {page_target.get('title')} ({page_target.get('url')})")

    def send_cdp(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Sends a raw CDP command and returns the result payload."""
        if not self.ws:
            raise RuntimeError("WebSocket is not connected.")
        self._msg_id += 1
        payload = {
            "id": self._msg_id,
            "method": method,
            "params": params or {},
        }
        self.ws.send(json.dumps(payload))
        while True:
            raw = self.ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == self._msg_id:
                return msg.get("result", {})

    def evaluate(self, js_expression: str) -> Any:
        res = self.send_cdp(
            "Runtime.evaluate",
            {
                "expression": js_expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        result = res.get("result", {})
        if "value" in result:
            return result["value"]
        return None

    def cdp_click_viewport(self, vx: float, vy: float, label: str = "") -> None:
        """Dispatches a native trusted mouse move + left click inside Chrome at viewport (vx, vy)
        without moving or stealing the user's OS mouse cursor.
        """
        jitter_x = random.uniform(-config.CLICK_JITTER_PX, config.CLICK_JITTER_PX)
        jitter_y = random.uniform(-config.CLICK_JITTER_PX, config.CLICK_JITTER_PX)
        tx = round(vx + jitter_x, 1)
        ty = round(vy + jitter_y, 1)
        print(f"[CDP Click] Clicking {label} at viewport ({tx}, {ty})")

        self.send_cdp(
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": tx, "y": ty},
        )
        time.sleep(0.03)
        self.send_cdp(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": tx,
                "y": ty,
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
            },
        )
        time.sleep(0.04)
        self.send_cdp(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": tx,
                "y": ty,
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
            },
        )

    def cdp_type_text(self, text: str) -> None:
        """Types text character-by-character via CDP without touching OS keyboard focus."""
        for ch in text:
            self.send_cdp("Input.insertText", {"text": ch})
            time.sleep(random.uniform(0.025, 0.055))

    def scroll_into_view_and_get_coords(
        self, js_element_getter: str
    ) -> Optional[Dict[str, Any]]:
        """Scrolls the DOM element returned by `js_element_getter` into view, waits briefly
        for layout to settle, and returns both its viewport (vx, vy) and OS screen (x, y) coords.
        """
        scroll_script = f"""
        (() => {{
            const el = {js_element_getter};
            if (!el) return false;
            el.scrollIntoView({{ behavior: 'instant', block: 'center', inline: 'center' }});
            return true;
        }})()
        """
        found = self.evaluate(scroll_script)
        if not found:
            return None

        time.sleep(0.15)

        coords_script = f"""
        (() => {{
            const el = {js_element_getter};
            if (!el) return null;
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return null;

            const vx = rect.left + rect.width / 2;
            const vy = rect.top + rect.height / 2;

            const dpr = window.devicePixelRatio || 1;
            const chromeTopBorder = window.outerHeight - (window.innerHeight * dpr);
            const chromeLeftBorder = (window.outerWidth - (window.innerWidth * dpr)) / 2;

            const screenX = window.screenX + chromeLeftBorder + vx * dpr;
            const screenY = window.screenY + chromeTopBorder + vy * dpr;

            return {{
                vx: vx,
                vy: vy,
                x: Math.round(screenX),
                y: Math.round(screenY),
                text: (el.innerText || el.value || '').replace(/\\s+/g, ' ').trim()
            }};
        }})()
        """
        res = self.evaluate(coords_script)
        if not res:
            return None
        return res

    def wait_for_coords(
        self,
        js_element_getter: str,
        timeout: float = config.ELEMENT_WAIT_TIMEOUT,
        poll_interval: float = 0.4,
    ) -> Optional[Dict[str, Any]]:
        """Polls the DOM up to `timeout` seconds until `js_element_getter` returns a visible
        element, then scrolls it into view and returns its coordinate dictionary.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if is_security_check_page(self):
                    wait_for_security_check_resolution(self)
                    deadline = time.time() + timeout
                coords = self.scroll_into_view_and_get_coords(js_element_getter)
                if coords is not None:
                    return coords
            except Exception:
                pass
            time.sleep(poll_interval)
        return None


def click_target(bridge: ChromeCDPBridge, coords: Dict[str, Any], label: str = "") -> None:
    """Clicks the target element using either cursor-free CDP input (default) or PyAutoGUI."""
    if getattr(config, "USE_PHYSICAL_MOUSE", False):
        jitter_x = random.randint(-config.CLICK_JITTER_PX, config.CLICK_JITTER_PX)
        jitter_y = random.randint(-config.CLICK_JITTER_PX, config.CLICK_JITTER_PX)
        target_x, target_y = int(coords["x"]) + jitter_x, int(coords["y"]) + jitter_y
        print(f"[PyAutoGUI] Clicking {label} at ({target_x}, {target_y})")
        pyautogui.moveTo(target_x, target_y, duration=config.MOUSE_MOVE_DURATION)
        pyautogui.click()
    else:
        bridge.cdp_click_viewport(float(coords["vx"]), float(coords["vy"]), label=label)


def notify_audible(urgent: bool = False) -> None:
    """Plays an audible beep sequence when availability is found."""
    if urgent:
        for _ in range(4):
            winsound.Beep(1200, 250)
            time.sleep(0.05)
    else:
        winsound.Beep(880, 400)
        time.sleep(0.1)
        winsound.Beep(1046, 400)


def notify_captcha_alert() -> None:
    """Plays a distinct two-tone alert sound when a security check / captcha appears."""
    for _ in range(3):
        winsound.Beep(950, 300)
        winsound.Beep(650, 300)
        time.sleep(0.1)


def is_security_check_page(bridge: ChromeCDPBridge) -> bool:
    """Detects if the Imperva / hCaptcha 'Additional security check is required' page is active."""
    script = """
    (() => {
        const secIframe = document.querySelector(
            '#main-iframe, iframe[src*="_Incapsula_Resource"], iframe[src*="hcaptcha"], iframe[src*="imperva"]'
        );
        if (secIframe) return true;

        const txt = (document.body?.innerText || '').toLowerCase();
        if (
            txt.includes('additional security check is required') ||
            txt.includes('complete the security check') ||
            txt.includes('powered by imperva')
        ) {
            return true;
        }
        return false;
    })()
    """
    try:
        return bool(bridge.evaluate(script))
    except Exception:
        return False


def wait_for_security_check_resolution(bridge: ChromeCDPBridge) -> None:
    """Stops all bot activity, alerts the user audibly, and waits until the user completes
    the security check and a normal booking page is back in Chrome.
    """
    if not is_security_check_page(bridge):
        return

    print("\n" + "=" * 70)
    print("[SECURITY CHECK DETECTED] Bot paused! Please complete the captcha in Chrome.")
    print("The bot will automatically resume once the booking page reloads.")
    print("=" * 70 + "\n")
    notify_captcha_alert()

    last_beep = time.time()
    while True:
        time.sleep(1.5)
        if time.time() - last_beep > 20.0:
            notify_captcha_alert()
            last_beep = time.time()

        if not is_security_check_page(bridge):
            normal_page = bridge.evaluate(
                "Boolean(document.querySelector('#test-centres-input, #test-centres-submit, a.test-centre-details-link, .BookingCalendar-datesBody, #slot-chosen-submit'))"
            )
            if normal_page:
                print("[RESUMED] Security check completed! Resuming bot in 2 seconds...")
                winsound.Beep(1046, 200)
                time.sleep(2.0)
                return


def is_search_limit_reached(bridge: ChromeCDPBridge) -> bool:
    """Checks if the 'Search limit reached: You've reached the maximum number of searches per hour'
    modal dialog is currently displayed.
    """
    script = """
    (() => {
        const okBtn = document.querySelector('#warning-ok, a[href*="dnSearchLimitWarningAck"]');
        if (okBtn) {
            const rect = okBtn.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) return true;
        }
        const dialogTitle = document.querySelector('#dialog-label');
        if (dialogTitle && (dialogTitle.innerText || '').toLowerCase().includes('search limit reached')) {
            return true;
        }
        return false;
    })()
    """
    try:
        return bool(bridge.evaluate(script))
    except Exception:
        return False


def handle_search_limit_if_present(bridge: ChromeCDPBridge) -> bool:
    """If the 'Search limit reached' modal is open, clicks 'Ok' to dismiss it and sleeps
    for `SEARCH_LIMIT_COOLDOWN_SECONDS` so the rolling hourly quota recovers.
    Returns True if rate limit was hit and handled.
    """
    if not is_search_limit_reached(bridge):
        return False

    print("\n" + "!" * 70)
    print("[HOURLY LIMIT REACHED] DVSA 'Search limit reached' dialog detected!")
    ok_coords = bridge.scroll_into_view_and_get_coords(
        "document.querySelector('#warning-ok, a[href*=\"dnSearchLimitWarningAck\"]')"
    )
    if ok_coords:
        click_target(bridge, ok_coords, label="Search Limit Modal 'Ok'")
        time.sleep(1.0)

    cooldown = getattr(config, "SEARCH_LIMIT_COOLDOWN_SECONDS", 900)
    mins = cooldown / 60.0
    print(f"[COOLDOWN] Pausing searches for {mins:.0f} minutes ({cooldown}s) to let hourly quota reset...")
    print("!" * 70 + "\n")
    time.sleep(cooldown)
    return True


def compute_smart_poll_delay() -> float:
    """Computes the delay before the next search to spread `MAX_SEARCHES_PER_HOUR` evenly
    across 3600 seconds, accounting for the rolling 60-minute window.
    """
    now = time.time()
    # Prune timestamps older than 3600 seconds (1 hour)
    while SEARCH_TIMESTAMPS and (now - SEARCH_TIMESTAMPS[0]) > 3600.0:
        SEARCH_TIMESTAMPS.popleft()

    max_per_hour = max(1, getattr(config, "MAX_SEARCHES_PER_HOUR", 36))
    base_interval = 3600.0 / max_per_hour  # e.g. 3600 / 36 = 100.0s
    jitter = getattr(config, "POLL_JITTER_SECONDS", 8.0)

    # If rolling window is already full, wait until the oldest search expires from the 1-hour window
    if len(SEARCH_TIMESTAMPS) >= max_per_hour:
        oldest_expiry = (SEARCH_TIMESTAMPS[0] + 3605.0) - now
        delay = max(base_interval, oldest_expiry) + random.uniform(2.0, jitter)
    else:
        delay = max(15.0, base_interval + random.uniform(-jitter, jitter))

    print(
        f"[Rate Pacer] Rolling hour usage: {len(SEARCH_TIMESTAMPS)}/{max_per_hour} searches "
        f"| Next search in {delay:.1f}s (~{3600.0 / base_interval:.0f}/hr pace)"
    )
    return delay


# Matches e.g. "Dundee – available tests around 03/03/2027" (even if the dash is mangled as \ufffd)
DATE_REGEX = re.compile(
    r"avai?li?able\s+tests\s+around\s+(\d{2})/(\d{2})/(\d{4})",
    re.IGNORECASE,
)


def run_postcode_search(bridge: ChromeCDPBridge, query: Optional[str] = None) -> bool:
    """Types a postcode/search query into the search input box and clicks 'Find test centres'."""
    wait_for_security_check_resolution(bridge)
    handle_search_limit_if_present(bridge)

    if query is not None:
        input_getter = """
        document.querySelector('#test-centres-input, input[name="testCentreName"], input[type="text"]')
        """
        coords = bridge.scroll_into_view_and_get_coords(input_getter)
        if not coords:
            if is_security_check_page(bridge):
                wait_for_security_check_resolution(bridge)
                coords = bridge.scroll_into_view_and_get_coords(input_getter)
            if not coords:
                print("[WARN] Could not find the postcode search input box.")
                return False

        click_target(bridge, coords, label=f"Search Input ('{query}')")
        if getattr(config, "USE_PHYSICAL_MOUSE", False):
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.05)
            pyautogui.press("backspace")
            pyautogui.write(query, interval=0.04)
        else:
            bridge.evaluate(
                """
                (() => {
                    const el = document.querySelector('#test-centres-input, input[name="testCentreName"], input[type="text"]');
                    if (el) { el.focus(); el.value = ''; }
                })()
                """
            )
            time.sleep(0.05)
            bridge.cdp_type_text(query)
        time.sleep(0.15)

    submit_getter = """
    (() => {
        const btn = document.querySelector('#test-centres-submit');
        if (btn) return btn;
        const allBtns = Array.from(document.querySelectorAll('input[type="submit"], button'));
        return allBtns.find(b => (b.value || b.innerText || '').toLowerCase().includes('find test centres')) || null;
    })()
    """
    btn_coords = bridge.scroll_into_view_and_get_coords(submit_getter)
    if not btn_coords:
        if is_security_check_page(bridge):
            wait_for_security_check_resolution(bridge)
            btn_coords = bridge.scroll_into_view_and_get_coords(submit_getter)
        if not btn_coords:
            print("[WARN] Could not find 'Find test centres' button.")
            return False

    click_target(bridge, btn_coords, label="Find test centres")
    SEARCH_TIMESTAMPS.append(time.time())
    time.sleep(config.PAGE_TRANSITION_DELAY)
    wait_for_security_check_resolution(bridge)
    if handle_search_limit_if_present(bridge):
        return False
    return True


def scan_locations(bridge: ChromeCDPBridge) -> List[Dict[str, Any]]:
    """Scans the green test centre banner links under 'Your search results'."""
    locations_json = json.dumps(config.TARGET_LOCATIONS)
    script = f"""
    (() => {{
        const targets = {locations_json};
        const links = Array.from(document.querySelectorAll(
            'a.test-centre-details-link, .test-centre-results a, ul.test-centre-results li a, a, h4, h2'
        ));
        const results = [];

        for (const loc of targets) {{
            const match = links.find(el => {{
                const txt = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                return txt.startsWith(loc) && (
                    txt.toLowerCase().includes('tests around') ||
                    txt.toLowerCase().includes('no tests found')
                );
            }});
            if (match) {{
                results.push({{
                    location: loc,
                    fullText: (match.innerText || '').replace(/\\s+/g, ' ').trim(),
                }});
            }}
        }}
        return results;
    }})()
    """
    return bridge.evaluate(script) or []


def click_location(bridge: ChromeCDPBridge, location_name: str) -> bool:
    """Finds the green header bar link for `location_name` and clicks it."""
    loc_escaped = json.dumps(location_name)
    getter = f"""
    (() => {{
        const loc = {loc_escaped};
        const links = Array.from(document.querySelectorAll(
            'a.test-centre-details-link, .test-centre-results a, a'
        ));
        const match = links.find(el => {{
            const h4 = el.querySelector('h4');
            const nameText = h4 ? h4.innerText.trim() : (el.innerText || '').replace(/\\s+/g, ' ').trim();
            const fullText = (el.innerText || '').replace(/\\s+/g, ' ').trim();
            return (nameText === loc || fullText.startsWith(loc)) && fullText.toLowerCase().includes('tests around');
        }});
        if (!match) return null;
        return match.querySelector('.test-centre-details, span.underline, h4') || match;
    }})()
    """
    coords = bridge.scroll_into_view_and_get_coords(getter)
    if not coords:
        print(f"[WARN] Could not determine coordinates for location: {location_name}")
        return False
    click_target(bridge, coords, label=f"Test Centre '{location_name}'")

    time.sleep(1.0)
    still_on_results = bridge.evaluate(
        "Boolean(document.querySelector('a.test-centre-details-link') && !document.querySelector('.BookingCalendar-datesBody, a.BookingCalendar-dateLink'))"
    )
    if still_on_results:
        coords_retry = bridge.scroll_into_view_and_get_coords(getter)
        if coords_retry:
            click_target(bridge, coords_retry, label=f"Test Centre '{location_name}' (confirm click)")

    return True


def select_earliest_calendar_date(bridge: ChromeCDPBridge) -> bool:
    """Finds all visible bookable white calendar date cells (e.g. '27', '5') on the
    Step 5 ('Test time') calendar, picks the earliest one, and clicks it.
    """
    getter = """
    (() => {
        let dateLinks = Array.from(document.querySelectorAll(
            'td.BookingCalendar-date--bookable a.BookingCalendar-dateLink, a.BookingCalendar-dateLink, td.bookable a'
        )).filter(el => {
            const cell = el.closest('td');
            if (cell && (
                cell.classList.contains('BookingCalendar-date--unavailable') ||
                cell.classList.contains('is-disabled')
            )) {
                return false;
            }
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        });

        if (dateLinks.length === 0) return null;

        dateLinks.sort((a, b) => {
            const da = a.getAttribute('data-date') || a.dataset?.date || '';
            const db = b.getAttribute('data-date') || b.dataset?.date || '';
            if (da && db) return da.localeCompare(db);
            return 0;
        });

        return dateLinks[0];
    })()
    """
    coords = bridge.wait_for_coords(getter, timeout=config.ELEMENT_WAIT_TIMEOUT)
    if not coords:
        print("[WARN] Could not find any bookable calendar dates on the page (timed out).")
        return False
    click_target(bridge, coords, label=f"Earliest Calendar Date ('{coords['text']}')")
    return True


def select_latest_time_slot(bridge: ChromeCDPBridge) -> bool:
    """Scrolls down to the 'Choose a time' panel for the selected date, finds all visible
    time slot cards (e.g. '9:17am £75'), and clicks the latest time.
    """
    getter = """
    (() => {
        const timeRegex = /\\b([01]?\\d|2[0-3])[:.]([0-5]\\d)(\\s*[ap]m)?\\b/i;

        const candidates = Array.from(document.querySelectorAll(
            '.SlotPicker-day.is-active label.SlotPicker-slot-label, label.SlotPicker-slot-label, label[for*="slot"]'
        )).filter(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const txt = (el.innerText || el.textContent || '').trim();
            return timeRegex.test(txt);
        });

        if (candidates.length === 0) return null;

        const parseMinutes = (el) => {
            const txt = (el.innerText || el.textContent || '').trim();
            const m = txt.match(/\\b([01]?\\d|2[0-3])[:.]([0-5]\\d)(\\s*([ap]m))?\\b/i);
            if (!m) return -1;
            let hours = parseInt(m[1], 10);
            const mins = parseInt(m[2], 10);
            const ampm = (m[4] || '').toLowerCase();
            if (ampm === 'pm' && hours < 12) hours += 12;
            if (ampm === 'am' && hours === 12) hours = 0;
            return hours * 60 + mins;
        };

        candidates.sort((a, b) => parseMinutes(a) - parseMinutes(b));
        return candidates[candidates.length - 1];
    })()
    """
    coords = bridge.wait_for_coords(getter, timeout=config.ELEMENT_WAIT_TIMEOUT)
    if not coords:
        print("[WARN] Could not find any visible time slot options (timed out).")
        return False
    click_target(bridge, coords, label=f"Latest Time Slot ('{coords['text']}')")
    return True


def click_continue_button(
    bridge: ChromeCDPBridge,
    step_name: str = "Continue",
    prefer_warning_modal: bool = False,
    timeout: float = config.ELEMENT_WAIT_TIMEOUT,
) -> bool:
    """Scrolls to and clicks the visible 'Continue >' button (#slot-chosen-submit or #slot-warning-continue)."""
    priority_list = (
        ["#slot-warning-continue", "button#slot-warning-continue", "#slot-chosen-submit"]
        if prefer_warning_modal
        else ["#slot-chosen-submit", "#slot-warning-continue", 'input[type="submit"]', 'button[type="submit"]', "button", "a.button"]
    )
    priority_json = json.dumps(priority_list)
    getter = f"""
    (() => {{
        const prioritySelectors = {priority_json};
        for (const sel of prioritySelectors) {{
            const els = Array.from(document.querySelectorAll(sel)).filter(el => {{
                if (el.disabled) return false;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const txt = (el.innerText || el.value || '').trim().toLowerCase();
                return txt.includes('continue') || sel.startsWith('#slot-');
            }});
            if (els.length > 0) return els[0];
        }}
        return null;
    }})()
    """
    coords = bridge.wait_for_coords(getter, timeout=timeout)
    if not coords:
        print(f"[WARN] Could not find '{step_name}' button.")
        return False
    click_target(bridge, coords, label=f"{step_name} ('{coords['text']}')")
    return True


def handle_calendar_and_slot_flow(bridge: ChromeCDPBridge) -> bool:
    """Executes Step 3 on the '5 Test time' page:
    1. Wait for the calendar page to load & click the earliest available white date cell (e.g. '27')
    2. Wait for 'Choose a time' slots to appear, scroll down, & click the latest time slot (e.g. '9:17am £75')
    3. Scroll to and press 'Continue >' (#slot-chosen-submit)
    4. Wait for the confirmation warning/next button and press 'Continue' again (#slot-warning-continue)
    """
    time.sleep(config.PAGE_TRANSITION_DELAY)

    print(f"[Step 3.1] Waiting up to {config.ELEMENT_WAIT_TIMEOUT:.0f}s for calendar dates to load...")
    if not select_earliest_calendar_date(bridge):
        return False

    time.sleep(0.5)

    print("[Step 3.2] Scrolling to 'Choose a time' & selecting latest time slot...")
    if not select_latest_time_slot(bridge):
        return False

    time.sleep(0.5)

    print("[Step 3.3] Clicking first 'Continue >' button...")
    if not click_continue_button(bridge, step_name="Continue (1)", prefer_warning_modal=False):
        return False

    time.sleep(0.8)
    print("[Step 3.4] Waiting for second 'Continue' button...")
    click_continue_button(bridge, step_name="Continue (2)", prefer_warning_modal=True, timeout=4.0)

    return True


def evaluate_date_action(location: str, day: int, month: int, year: int) -> str:
    """Returns 'book', 'notify', or 'ignore' for a location and parsed (day, month, year)."""
    if location in getattr(config, "ACCEPT_ANY_DATE_LOCATIONS", []):
        return "book"
    if (month, year) in config.AUTO_BOOK_MONTHS:
        return "book"
    if (month, year) in config.NOTIFY_ONLY_MONTHS:
        return "notify"
    return "ignore"


def check_current_results(bridge: ChromeCDPBridge) -> bool:
    """Scans the currently displayed search results and returns True if a booking flow completed."""
    wait_for_security_check_resolution(bridge)
    if handle_search_limit_if_present(bridge):
        return False

    matches = scan_locations(bridge)
    for item in matches:
        loc = item["location"]
        full_text = item["fullText"]
        m = DATE_REGEX.search(full_text)
        if not m:
            print(f"[INFO] {loc}: No dates available ({full_text})")
            continue

        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        date_str = f"{day:02d}/{month:02d}/{year:04d}"
        action = evaluate_date_action(loc, day, month, year)

        if action == "book":
            print(f"[MATCH - AUTO BOOK] {loc} has tests around {date_str}!")
            notify_audible(urgent=True)
            if click_location(bridge, loc):
                if handle_calendar_and_slot_flow(bridge):
                    print("[SUCCESS] Reached the next form page! Stopping bot for manual handling.")
                    return True
        elif action == "notify":
            print(f"[MATCH - NOTIFY ONLY] {loc} has tests around {date_str} (01/2027)")
            notify_audible(urgent=False)
        else:
            print(f"[INFO] {loc}: available around {date_str} (outside target months)")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid Chrome CDP Booking Bot")
    parser.add_argument(
        "--test-calendar",
        action="store_true",
        help="Immediately test clicking the earliest calendar date, latest time slot, and Continue on the currently open 'Test time' page.",
    )
    args = parser.parse_args()

    bridge = ChromeCDPBridge()
    bridge.connect()

    mode_str = "Physical Mouse (PyAutoGUI)" if getattr(config, "USE_PHYSICAL_MOUSE", False) else "100% Cursor-Free (CDP Native Input)"
    print(f"[Mode] {mode_str} | Target Pace: {config.MAX_SEARCHES_PER_HOUR} searches/hour")

    if args.test_calendar:
        print("[TEST MODE] Running calendar + time slot + continue flow on current page...")
        handle_calendar_and_slot_flow(bridge)
        return

    print("Monitoring locations for availability...")
    if check_current_results(bridge):
        return

    while True:
        if config.SEARCH_QUERIES:
            for query in config.SEARCH_QUERIES:
                if run_postcode_search(bridge, query=query):
                    if check_current_results(bridge):
                        return
                delay = compute_smart_poll_delay()
                time.sleep(delay)
        else:
            delay = compute_smart_poll_delay()
            time.sleep(delay)
            if run_postcode_search(bridge, query=None):
                if check_current_results(bridge):
                    return


if __name__ == "__main__":
    main()
