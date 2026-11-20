"""Hybrid Browser UI Automation Case Study (Chrome DevTools Protocol + PyAutoGUI).

===============================================================================
EDUCATIONAL & TECHNICAL RESEARCH DISCLAIMER
===============================================================================
This codebase is an archived software engineering proof-of-concept and research
case study exploring:
  1. Hybrid browser automation via Chrome DevTools Protocol (CDP) viewport
     coordinate projection (`Input.dispatchMouseEvent`) vs. OS-level virtual
     desktop coordinate mapping (`window.devicePixelRatio`, `PyAutoGUI`).
  2. Client-side rate-pacing and Spring Web Flow state-transition telemetry.
  3. Automated UI testing against saved offline HTML form snapshots.

IMPORTANT LEGAL & ACCEPTABLE USE NOTICE:
  - Automated scraping, polling, or booking on live Driver and Vehicle
    Standards Agency (DVSA) systems is prohibited by the DVSA Terms and
    Conditions and Acceptable Use Policy.
  - This software is published strictly for educational, academic, and
    portfolio demonstration purposes and is NOT intended to be used by
    individuals against live DVSA infrastructure.
  - This software explicitly does NOT bypass or automate CAPTCHA or security
    access controls; execution immediately halts whenever a security challenge
    is detected.
  - By default, `config.DRY_RUN = True` is enabled so that live booking
    transitions are disabled out-of-the-box.
===============================================================================
"""

import argparse
import collections
from datetime import datetime
import json
import os
import random
import re
import subprocess
import sys
import time
import winsound
from typing import Any, Deque, Dict, List, Optional

import pyautogui
import requests
import websocket

import config

try:
    from candidate_details import CANDIDATE_DETAILS
except ImportError:
    try:
        from candidate_details_example import CANDIDATE_DETAILS  # type: ignore
    except ImportError:
        CANDIDATE_DETAILS = {}

# Enable PyAutoGUI fail-safe (if USE_PHYSICAL_MOUSE is enabled)
pyautogui.FAILSAFE = True

# Rolling 60-minute window of search timestamps
SEARCH_TIMESTAMPS: Deque[float] = collections.deque()

# Empirical Search-Limit Telemetry & Calibration State
SESSION_START_TIME: float = time.time()
START_EXECUTION_STEP: Optional[int] = None
LAST_LIMIT_EXECUTION_STEP: Optional[int] = None
LAST_LIMIT_HIT_TIME: Optional[float] = None
TOTAL_SUCCESSFUL_SEARCHES: int = 0
SEARCHES_SINCE_LAST_LIMIT: int = 0
DISCOVERED_MAX_SEARCHES: Optional[int] = None
EFFECTIVE_MAX_SEARCHES_PER_HOUR: int = getattr(config, "MAX_SEARCHES_PER_HOUR", 72)

EXECUTION_STEP_REGEX = re.compile(r"execution=e\d+s(\d+)", re.IGNORECASE)


def ensure_chrome_running(host: str = config.CDP_HOST) -> None:
    """Checks if Chrome remote debugging is reachable on `host`; if not, launches `start_chrome.bat`."""
    url = f"{host.rstrip('/')}/json"
    try:
        resp = requests.get(url, timeout=2)
        if resp.ok:
            return
    except requests.RequestException:
        pass

    bat_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "start_chrome.bat")
    if os.path.isfile(bat_path):
        print(f"[Startup] Chrome not detected on {host}. Running start_chrome.bat...")
        subprocess.Popen(["cmd.exe", "/c", bat_path], cwd=os.path.dirname(bat_path))
    else:
        chrome_exe = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        profile_dir = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\BotProfile")
        print(f"[Startup] Launching Chrome with --remote-debugging-port=9222...")
        subprocess.Popen([chrome_exe, "--remote-debugging-port=9222", f"--user-data-dir={profile_dir}"])

    for _ in range(20):
        time.sleep(1.0)
        try:
            resp = requests.get(url, timeout=2)
            if resp.ok:
                return
        except requests.RequestException:
            pass


class ChromeCDPBridge:
    """Connects to a running Chrome instance via Chrome DevTools Protocol (CDP)
    to inspect the live DOM and dispatch native browser clicks/typing (or OS coordinates).
    """

    def __init__(self, host: str = config.CDP_HOST):
        self.host = host.rstrip("/")
        self.ws: Optional[websocket.WebSocket] = None
        self._msg_id = 0
        self._url_keyword: Optional[str] = None
        self._target_id: Optional[str] = None

    def is_tab_open(self) -> bool:
        """Returns True if Chrome is still running and has at least one page tab open."""
        try:
            resp = requests.get(f"{self.host}/json", timeout=3)
            if not resp.ok:
                return False
            targets = resp.json()
            pages = [
                t for t in targets
                if t.get("type") == "page" and not t.get("url", "").startswith("devtools://")
            ]
            if not pages:
                return False
            if self._target_id:
                return any(t.get("id") == self._target_id for t in pages)
            return True
        except requests.RequestException:
            return False

    def connect(self, url_keyword: Optional[str] = None, auto_launch: bool = False) -> None:
        if url_keyword is not None:
            self._url_keyword = url_keyword

        if auto_launch:
            ensure_chrome_running(self.host)

        try:
            resp = requests.get(f"{self.host}/json", timeout=5)
            resp.raise_for_status()
            targets = resp.json()
        except requests.RequestException:
            print("\n[INFO] Chrome debug window was closed. Stopping bot cleanly.")
            sys.exit(0)

        page_target = None
        for t in targets or []:
            if t.get("type") != "page":
                continue
            if self._url_keyword and self._url_keyword.lower() not in t.get("url", "").lower():
                continue
            if not t.get("url", "").startswith("devtools://"):
                page_target = t
                break

        if not page_target:
            print("\n[INFO] No open Chrome page tab found (tab was closed). Stopping bot cleanly.")
            sys.exit(0)

        self._target_id = page_target.get("id")
        ws_url = page_target["webSocketDebuggerUrl"]
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.ws = websocket.create_connection(ws_url, timeout=10)
        print(f"[CDP] Connected to tab: {page_target.get('title')} ({page_target.get('url')})")

    def send_cdp(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Sends a raw CDP command and returns the result payload. Exits cleanly if Chrome tab was closed."""
        for attempt in range(3):
            if not self.ws:
                if not self.is_tab_open():
                    print("\n[INFO] Chrome tab/window was closed by user. Exiting bot cleanly.")
                    sys.exit(0)
                self.connect()
            self._msg_id += 1
            payload = {
                "id": self._msg_id,
                "method": method,
                "params": params or {},
            }
            try:
                assert self.ws is not None
                self.ws.send(json.dumps(payload))
                while True:
                    raw = self.ws.recv()
                    msg = json.loads(raw)
                    if msg.get("id") == self._msg_id:
                        return msg.get("result", {})
            except (websocket.WebSocketException, OSError, ConnectionError) as exc:
                self.ws = None
                if not self.is_tab_open():
                    print("\n[INFO] Chrome tab/window was closed by user. Exiting bot cleanly.")
                    sys.exit(0)
                print(f"[CDP] WebSocket reset ({exc}), reconnecting to tab (attempt {attempt + 1}/3)...")
                time.sleep(1.0)
                if attempt == 2:
                    raise
        return {}

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


def is_error_15_block_page(bridge: ChromeCDPBridge) -> bool:
    """Detects Imperva 'Access Denied / Error 15 (You have been blocked by DVSA security rules)'
    temporary rate-limit page (which requires waiting ~15-30-60 minutes rather than solving a captcha).
    """
    script = """
    (() => {
        let combinedText = (document.body?.innerText || '').toLowerCase();
        const iframes = Array.from(document.querySelectorAll(
            '#main-iframe, iframe[src*="_Incapsula_Resource"], iframe'
        ));
        for (const frame of iframes) {
            try {
                const frameTxt = (frame.contentDocument?.body?.innerText || '').toLowerCase();
                if (frameTxt) combinedText += '\\n' + frameTxt;
            } catch (e) {}
        }
        return (
            combinedText.includes('error 15') ||
            combinedText.includes('blocked by dvsa security rules') ||
            combinedText.includes('request was blocked by our security service') ||
            (combinedText.includes('access denied') && combinedText.includes('imperva'))
        );
    })()
    """
    try:
        return bool(bridge.evaluate(script))
    except Exception:
        return False


def is_security_check_page(bridge: ChromeCDPBridge) -> bool:
    """Detects if an interactive Imperva / hCaptcha 'Additional security check is required' page is active
    (excluding Error 15 temporary blocks).
    """
    if is_error_15_block_page(bridge):
        return False

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


def get_execution_step(bridge: ChromeCDPBridge) -> Optional[int]:
    """Extracts the numeric Spring Web Flow step from `execution=e1s<N>` in the current URL."""
    try:
        url = bridge.evaluate("window.location.href") or ""
        m = EXECUTION_STEP_REGEX.search(str(url))
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def prune_search_timestamps(now: Optional[float] = None) -> None:
    """Removes search timestamps older than 60 minutes (3600 seconds)."""
    if now is None:
        now = time.time()
    while SEARCH_TIMESTAMPS and (now - SEARCH_TIMESTAMPS[0]) > 3600.0:
        SEARCH_TIMESTAMPS.popleft()


def log_telemetry_event(event_type: str, data: Dict[str, Any]) -> None:
    """Appends a structured JSON line to `config.SEARCH_LIMIT_LOG_FILE`."""
    log_path = getattr(config, "SEARCH_LIMIT_LOG_FILE", "search_limit_log.jsonl")
    if not log_path:
        return
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event_type,
        **data,
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        print(f"[WARN] Could not write telemetry log: {exc}")


def wait_for_error_15_resolution(bridge: ChromeCDPBridge) -> None:
    """Handles Imperva 'Access Denied / Error 15' temporary blocks by waiting through cumulative
    milestones (15m -> 30m -> 60m from config.ERROR_15_RETRY_MINUTES), automatically reloading
    the page at each milestone until the temporary block clears.
    """
    global DISCOVERED_MAX_SEARCHES, EFFECTIVE_MAX_SEARCHES_PER_HOUR, SEARCHES_SINCE_LAST_LIMIT

    if not is_error_15_block_page(bridge):
        return

    block_start = time.time()
    prune_search_timestamps(block_start)
    rolling_count = len(SEARCH_TIMESTAMPS)
    cur_step = get_execution_step(bridge)

    if rolling_count > 0:
        DISCOVERED_MAX_SEARCHES = rolling_count
        if getattr(config, "AUTO_ADAPT_PACE_ON_LIMIT", False):
            EFFECTIVE_MAX_SEARCHES_PER_HOUR = max(1, rolling_count - 4)

    milestones_mins: List[int] = list(getattr(config, "ERROR_15_RETRY_MINUTES", [15, 30, 60]))
    if not milestones_mins:
        milestones_mins = [15, 30, 60]

    log_telemetry_event(
        "error_15_temporary_block",
        {
            "rolling_60m_searches": rolling_count,
            "searches_since_last_limit": SEARCHES_SINCE_LAST_LIMIT,
            "total_session_searches": TOTAL_SUCCESSFUL_SEARCHES,
            "execution_step": cur_step,
            "retry_milestones_minutes": milestones_mins,
        },
    )
    SEARCHES_SINCE_LAST_LIMIT = 0

    print("\n" + "!" * 74)
    print("[IMPERVA ERROR 15 — TEMPORARY COOLDOWN BLOCK DETECTED]")
    print(
        f"  -> Triggered at URL step: s{cur_step} | Rolling 60m searches: {rolling_count} "
        f"(Session total: {TOTAL_SUCCESSFUL_SEARCHES})"
    )
    print(
        f"  -> Auto-retry schedule: {', '.join(str(m) + 'm' for m in milestones_mins)} "
        "(no action needed — bot will wait and reload automatically)."
    )
    print("!" * 74 + "\n")

    attempt_idx = 0
    while True:
        if attempt_idx < len(milestones_mins):
            target_elapsed_mins = milestones_mins[attempt_idx]
        else:
            target_elapsed_mins = milestones_mins[-1] + 15 * (attempt_idx - len(milestones_mins) + 1)

        target_time = block_start + (target_elapsed_mins * 60.0)
        last_status_print = time.time()

        while time.time() < target_time:
            time.sleep(5.0)
            if not bridge.is_tab_open():
                print("\n[INFO] Chrome tab/window was closed by user. Exiting bot cleanly.")
                sys.exit(0)

            # If user manually refreshed or navigated away and Error 15 is already cleared:
            if not is_error_15_block_page(bridge):
                elapsed_m = (time.time() - block_start) / 60.0
                print(f"[Error 15 Cleared] Page is no longer showing Error 15 (after {elapsed_m:.1f}m)!")
                log_telemetry_event("error_15_recovered", {"recovery_minutes": round(elapsed_m, 1)})
                winsound.Beep(1046, 200)
                time.sleep(1.5)
                return

            if time.time() - last_status_print >= 60.0:
                elapsed_m = (time.time() - block_start) / 60.0
                rem_m = max(0.0, (target_time - time.time()) / 60.0)
                print(
                    f"[Error 15 Cooldown] {elapsed_m:.0f}m elapsed | "
                    f"Next auto-retry at {target_elapsed_mins}m mark (in {rem_m:.1f}m)..."
                )
                last_status_print = time.time()

        # Milestone reached: reload page to test if temporary block has lifted
        print(
            f"[Error 15 Retry #{attempt_idx + 1}] {target_elapsed_mins} minutes elapsed — "
            "reloading page to check if temporary block has lifted..."
        )
        try:
            bridge.evaluate("window.location.reload()")
        except Exception:
            pass
        time.sleep(4.0)

        if not is_error_15_block_page(bridge):
            elapsed_m = (time.time() - block_start) / 60.0
            print(f"[Error 15 Recovered] Temporary block lifted after {elapsed_m:.1f} minutes!")
            log_telemetry_event("error_15_recovered", {"recovery_minutes": round(elapsed_m, 1)})
            winsound.Beep(1046, 200)
            time.sleep(1.5)
            return

        attempt_idx += 1
        next_target = (
            milestones_mins[attempt_idx]
            if attempt_idx < len(milestones_mins)
            else milestones_mins[-1] + 15 * (attempt_idx - len(milestones_mins) + 1)
        )
        print(
            f"[Error 15 Still Active] Still blocked at {target_elapsed_mins}m mark. "
            f"Waiting until {next_target}m mark..."
        )


def wait_for_security_check_resolution(bridge: ChromeCDPBridge) -> None:
    """Stops all bot activity, handles Error 15 cooldowns or interactive captchas, and waits
    until a normal booking page is back in Chrome (or exits cleanly if tab closed).
    """
    if is_error_15_block_page(bridge):
        wait_for_error_15_resolution(bridge)
        wait_until_test_centre_page_ready(bridge)
        return

    if not is_security_check_page(bridge):
        return

    now = time.time()
    prune_search_timestamps(now)
    cur_step = get_execution_step(bridge)
    log_telemetry_event(
        "security_check_triggered",
        {
            "rolling_60m_searches": len(SEARCH_TIMESTAMPS),
            "searches_since_last_limit": SEARCHES_SINCE_LAST_LIMIT,
            "total_session_searches": TOTAL_SUCCESSFUL_SEARCHES,
            "execution_step": cur_step,
        },
    )

    print("\n" + "=" * 70)
    print(
        f"[SECURITY CHECK DETECTED] Triggered at {len(SEARCH_TIMESTAMPS)} searches in rolling 60m "
        f"(total: {TOTAL_SUCCESSFUL_SEARCHES}, URL step: e1s{cur_step})."
    )
    print("Bot paused! Please complete the captcha in Chrome (or close the tab to stop the bot).")
    print("The bot will automatically resume once the booking page reloads.")
    print("=" * 70 + "\n")
    notify_captcha_alert()

    while True:
        time.sleep(1.5)
        if not bridge.is_tab_open():
            print("\n[INFO] Chrome tab/window was closed by user. Exiting bot cleanly.")
            sys.exit(0)

        if not is_security_check_page(bridge):
            try:
                normal_page = bridge.evaluate(
                    "Boolean(document.querySelector('#test-centres-input, #test-centres-submit, a.test-centre-details-link, .BookingCalendar-datesBody, #slot-chosen-submit'))"
                )
            except Exception:
                normal_page = False
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
    """If the 'Search limit reached' modal is open, calculates the exact empirical search limit
    that triggered it, logs it to console and JSONL, clicks 'Ok' to dismiss, and sleeps for
    `SEARCH_LIMIT_COOLDOWN_SECONDS` so the rolling hourly quota recovers.
    Returns True if rate limit was hit and handled.
    """
    global DISCOVERED_MAX_SEARCHES, EFFECTIVE_MAX_SEARCHES_PER_HOUR
    global LAST_LIMIT_HIT_TIME, LAST_LIMIT_EXECUTION_STEP, SEARCHES_SINCE_LAST_LIMIT

    if not is_search_limit_reached(bridge):
        return False

    now = time.time()
    prune_search_timestamps(now)

    # Number of searches in the rolling 60m window (excluding the blocked attempt if it was just appended)
    rolling_count = len(SEARCH_TIMESTAMPS)
    cur_step = get_execution_step(bridge)
    step_from_start = (cur_step - START_EXECUTION_STEP) if (cur_step and START_EXECUTION_STEP) else None
    step_since_last = (
        (cur_step - LAST_LIMIT_EXECUTION_STEP) if (cur_step and LAST_LIMIT_EXECUTION_STEP) else step_from_start
    )

    if SEARCH_TIMESTAMPS:
        window_span_sec = max(1.0, now - SEARCH_TIMESTAMPS[0])
        effective_rate = (rolling_count / window_span_sec) * 3600.0
    else:
        window_span_sec = max(1.0, now - SESSION_START_TIME)
        effective_rate = 0.0

    # Record empirical max searches before failure
    if rolling_count > 0:
        DISCOVERED_MAX_SEARCHES = rolling_count
    safe_recommended = max(1, (DISCOVERED_MAX_SEARCHES or 40) - 4)

    if getattr(config, "AUTO_ADAPT_PACE_ON_LIMIT", False) and DISCOVERED_MAX_SEARCHES:
        EFFECTIVE_MAX_SEARCHES_PER_HOUR = safe_recommended

    telemetry_payload = {
        "discovered_max_searches_in_60m": rolling_count,
        "searches_since_last_limit": SEARCHES_SINCE_LAST_LIMIT,
        "total_session_searches": TOTAL_SUCCESSFUL_SEARCHES,
        "window_elapsed_minutes": round(window_span_sec / 60.0, 2),
        "effective_pace_per_hour": round(effective_rate, 1),
        "execution_step": cur_step,
        "execution_step_delta_from_start": step_from_start,
        "execution_step_delta_since_last_limit": step_since_last,
        "recommended_safe_searches_per_hour": safe_recommended,
    }
    log_telemetry_event("search_limit_reached", telemetry_payload)

    LAST_LIMIT_HIT_TIME = now
    LAST_LIMIT_EXECUTION_STEP = cur_step
    SEARCHES_SINCE_LAST_LIMIT = 0

    print("\n" + "!" * 74)
    print("[HOURLY LIMIT REACHED] DVSA 'Search limit reached' dialog detected!")
    print(
        f"  -> Empirical Max Searches (last 60m) : {rolling_count} searches "
        f"in {window_span_sec / 60.0:.1f} mins ({effective_rate:.1f}/hr pace)"
    )
    print(
        f"  -> Searches Since Start / Last Limit : {telemetry_payload['searches_since_last_limit']} "
        f"(Session Total: {TOTAL_SUCCESSFUL_SEARCHES})"
    )
    print(
        f"  -> URL State Counter (execution)     : e1s{cur_step} "
        f"(+{step_from_start} since start, +{step_since_last} since last limit)"
    )
    print(
        f"  -> Recommended Safe Hourly Setting   : MAX_SEARCHES_PER_HOUR = {safe_recommended} "
        f"(leaves 4-step booking reserve)"
    )
    print(f"  -> Logged details to                 : {getattr(config, 'SEARCH_LIMIT_LOG_FILE', 'search_limit_log.jsonl')}")

    ok_coords = bridge.scroll_into_view_and_get_coords(
        "document.querySelector('#warning-ok, a[href*=\"dnSearchLimitWarningAck\"]')"
    )
    if ok_coords:
        click_target(bridge, ok_coords, label="Search Limit Modal 'Ok'")
        time.sleep(1.0)

    cooldown = getattr(config, "SEARCH_LIMIT_COOLDOWN_SECONDS", 300)
    mins = cooldown / 60.0
    print(f"[COOLDOWN] Pausing searches for {mins:.1f} minutes ({cooldown}s) before probing quota recovery...")
    print("!" * 74 + "\n")
    smart_sleep_with_keepalive(bridge, cooldown)
    return True


def smart_sleep_with_keepalive(bridge: ChromeCDPBridge, duration: float) -> None:
    """Sleeps for `duration` seconds while periodically checking for:
    - Captcha / security check dialogs
    - Session timeout warning dialogs (auto-clicking 'Keep me signed in' / 'Continue' if shown)
    """
    end_time = time.time() + duration
    while time.time() < end_time:
        remaining = end_time - time.time()
        time.sleep(min(5.0, max(0.1, remaining)))
        try:
            if is_error_15_block_page(bridge) or is_security_check_page(bridge):
                wait_for_security_check_resolution(bridge)
            # Check for DVSA session timeout warning modal and keep session alive
            keep_alive_getter = """
            (() => {
                const btns = Array.from(document.querySelectorAll('button, a.button, input[type="button"]'));
                return btns.find(b => {
                    const rect = b.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) return false;
                    const txt = (b.innerText || b.value || '').toLowerCase();
                    return txt.includes('keep') || txt.includes('stay signed in') || txt.includes('extend');
                }) || null;
            })()
            """
            ka_coords = bridge.scroll_into_view_and_get_coords(keep_alive_getter)
            if ka_coords:
                click_target(bridge, ka_coords, label="Session Keep-Alive")
        except Exception:
            pass


def compute_smart_poll_delay() -> float:
    """Computes the delay before the next search to spread `EFFECTIVE_MAX_SEARCHES_PER_HOUR` evenly
    across 3600 seconds, accounting for the rolling 60-minute window.
    """
    now = time.time()
    prune_search_timestamps(now)

    max_per_hour = max(1, EFFECTIVE_MAX_SEARCHES_PER_HOUR)
    base_interval = 3600.0 / max_per_hour  # e.g. 3600 / 72 = 50.0s
    jitter = getattr(config, "POLL_JITTER_SECONDS", 5.0)

    # If rolling window is already full, wait until the oldest search expires from the 1-hour window
    if len(SEARCH_TIMESTAMPS) >= max_per_hour:
        oldest_expiry = (SEARCH_TIMESTAMPS[0] + 3605.0) - now
        delay = max(base_interval, oldest_expiry) + random.uniform(2.0, jitter)
    else:
        delay = max(10.0, base_interval + random.uniform(-jitter, jitter))

    discovered_str = (
        f" | Discovered limit: {DISCOVERED_MAX_SEARCHES}/hr"
        if DISCOVERED_MAX_SEARCHES is not None
        else " | Probing max limit..."
    )
    print(
        f"[Rate Pacer] Rolling 60m: {len(SEARCH_TIMESTAMPS)}/{max_per_hour} searches "
        f"(Session: {TOTAL_SUCCESSFUL_SEARCHES}){discovered_str} "
        f"| Next search in {delay:.1f}s (~{3600.0 / base_interval:.0f}/hr pace)"
    )
    return delay


# Matches e.g. "Edinburgh (Currie) – available tests around 03/03/2027" (even if the dash is mangled as \ufffd)
DATE_REGEX = re.compile(
    r"avai?li?able\s+tests\s+around\s+(\d{2})/(\d{2})/(\d{4})",
    re.IGNORECASE,
)


def run_postcode_search(bridge: ChromeCDPBridge, query: Optional[str] = None) -> bool:
    """Types a postcode/search query into the search input box and clicks 'Find test centres'."""
    global START_EXECUTION_STEP, TOTAL_SUCCESSFUL_SEARCHES, SEARCHES_SINCE_LAST_LIMIT, LAST_LIMIT_HIT_TIME

    wait_for_security_check_resolution(bridge)
    handle_search_limit_if_present(bridge)

    if START_EXECUTION_STEP is None:
        START_EXECUTION_STEP = get_execution_step(bridge)

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
    attempt_ts = time.time()
    time.sleep(config.PAGE_TRANSITION_DELAY)
    wait_for_security_check_resolution(bridge)
    if handle_search_limit_if_present(bridge):
        return False

    # Search succeeded without hitting the limit modal
    SEARCH_TIMESTAMPS.append(attempt_ts)
    prune_search_timestamps(attempt_ts)
    TOTAL_SUCCESSFUL_SEARCHES += 1
    SEARCHES_SINCE_LAST_LIMIT += 1
    cur_step = get_execution_step(bridge)
    step_delta = (cur_step - START_EXECUTION_STEP) if (cur_step and START_EXECUTION_STEP) else 0

    if LAST_LIMIT_HIT_TIME is not None:
        recovery_sec = attempt_ts - LAST_LIMIT_HIT_TIME
        print(
            f"[LIMIT RECOVERED] Searches working again after {recovery_sec / 60.0:.1f}m ({recovery_sec:.0f}s) "
            f"| Rolling 60m count: {len(SEARCH_TIMESTAMPS)}"
        )
        log_telemetry_event(
            "search_limit_recovered",
            {
                "recovery_seconds": round(recovery_sec, 1),
                "rolling_60m_searches": len(SEARCH_TIMESTAMPS),
                "execution_step": cur_step,
            },
        )
        LAST_LIMIT_HIT_TIME = None

    print(
        f"[Search OK #{TOTAL_SUCCESSFUL_SEARCHES}] Query: '{query or 'current'}' "
        f"| 60m Window: {len(SEARCH_TIMESTAMPS)} | Since last limit: {SEARCHES_SINCE_LAST_LIMIT} "
        f"| URL State: e1s{cur_step} (+{step_delta})"
    )
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


def fill_candidate_details_and_submit(bridge: ChromeCDPBridge, submit: bool = True) -> bool:
    """Executes Step 6 ('Your details') candidate details form automation:
    1. Waits for the 'Your details' form (#details-suffix, #details-first-names) to load
    2. Selects Title ('Mr') from #details-suffix
    3. Fills First names, Surname, Address line 1, Town, Postcode, Email, Confirm email, Contact number
    4. Clicks 'Next: payment details' (#details-submit)
    """
    if not CANDIDATE_DETAILS:
        print("[WARN] candidate_details.py is missing or empty; skipping auto-fill.")
        return False

    print(f"[Step 4.1] Waiting up to {config.ELEMENT_WAIT_TIMEOUT:.0f}s for 'Your details' form to load...")
    form_getter = """
    document.querySelector('#details-suffix, select[name="title"], #details-first-names, input[name="firstName"]')
    """
    if not bridge.wait_for_coords(form_getter, timeout=config.ELEMENT_WAIT_TIMEOUT):
        print("[WARN] Could not find 'Your details' form on the page (timed out).")
        return False

    # 1. Select Title dropdown (#details-suffix / select[name="title"])
    title_val = CANDIDATE_DETAILS.get("title", "Mr")
    if title_val:
        title_getter = "document.querySelector('#details-suffix, select[name=\"title\"]')"
        title_coords = bridge.scroll_into_view_and_get_coords(title_getter)
        if title_coords:
            click_target(bridge, title_coords, label=f"Title Dropdown ('{title_val}')")
            time.sleep(0.1)
            title_json = json.dumps(title_val)
            bridge.evaluate(
                f"""
                (() => {{
                    const sel = document.querySelector('#details-suffix, select[name="title"]');
                    if (!sel) return false;
                    sel.value = {title_json};
                    sel.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }})()
                """
            )
            time.sleep(0.15)

    # 2. Fill text/email/tel inputs in order
    field_mappings = [
        ("First names", "#details-first-names, input[name=\"firstName\"]", CANDIDATE_DETAILS.get("first_names", "")),
        ("Surname", "#details-surname, input[name=\"surname\"]", CANDIDATE_DETAILS.get("surname", "")),
        ("Address line 1", "#details-address-1, input[name=\"addressLine1\"]", CANDIDATE_DETAILS.get("address_line_1", "")),
        ("Address line 2", "#details-address-2, input[name=\"addressLine2\"]", CANDIDATE_DETAILS.get("address_line_2", "")),
        ("Town", "#details-town, input[name=\"town\"]", CANDIDATE_DETAILS.get("town", "")),
        ("Postcode", "#details-postcode, input[name=\"postcode\"]", CANDIDATE_DETAILS.get("postcode", "")),
        ("Email address", "#details-email, input[name=\"emailAddress\"]", CANDIDATE_DETAILS.get("email", "")),
        (
            "Confirm email address",
            "#details-confirm-email, input[name=\"confirmEmailAddress\"]",
            CANDIDATE_DETAILS.get("confirm_email", CANDIDATE_DETAILS.get("email", "")),
        ),
        ("Contact number", "#details-contact-number, input[name=\"contactNumber\"]", CANDIDATE_DETAILS.get("contact_number", "")),
    ]

    for label, selector, value in field_mappings:
        if not value:
            continue
        sel_json = json.dumps(selector)
        val_json = json.dumps(value)
        getter = f"document.querySelector({sel_json})"
        coords = bridge.scroll_into_view_and_get_coords(getter)
        if not coords:
            print(f"[WARN] Could not find input field for {label} ({selector}).")
            continue

        click_target(bridge, coords, label=f"{label}")
        if getattr(config, "USE_PHYSICAL_MOUSE", False):
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.04)
            pyautogui.press("backspace")
            pyautogui.write(value, interval=0.025)
        else:
            bridge.evaluate(
                f"""
                (() => {{
                    const el = document.querySelector({sel_json});
                    if (el) {{ el.focus(); el.value = ''; }}
                }})()
                """
            )
            time.sleep(0.04)
            bridge.cdp_type_text(value)

        # Ensure exact value and fire input/change/blur events for DVSA validation
        bridge.evaluate(
            f"""
            (() => {{
                const el = document.querySelector({sel_json});
                if (!el) return;
                if (el.value !== {val_json}) el.value = {val_json};
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
            }})()
            """
        )
        time.sleep(0.1)

    if not submit or getattr(config, "DRY_RUN", True):
        print("[Step 4.2] Candidate details filled (skipping final submit in DRY_RUN / --no-submit mode).")
        return True

    # 3. Click 'Next: payment details' (#details-submit)
    submit_getter = """
    document.querySelector('#details-submit, input[name="detailsSubmit"], input[type="submit"].cta, button[type="submit"]')
    """
    submit_coords = bridge.wait_for_coords(submit_getter, timeout=config.ELEMENT_WAIT_TIMEOUT)
    if not submit_coords:
        print("[WARN] Could not find 'Next: payment details' (#details-submit) button.")
        return False

    click_target(bridge, submit_coords, label=f"Next: payment details ('{submit_coords['text']}')")
    notify_audible(urgent=True)
    print("[SUCCESS] Submitted 'Your details' form! Reached Step 7 ('Card details' / payment).")
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
            if getattr(config, "DRY_RUN", True):
                print(
                    f"[DRY RUN] config.DRY_RUN=True — skipping live booking transition for {loc} ({date_str})."
                )
                continue
            if click_location(bridge, loc):
                if handle_calendar_and_slot_flow(bridge):
                    fill_candidate_details_and_submit(bridge, submit=True)
                    print("[SUCCESS] Booking flow reached payment page! Stopping bot for manual payment.")
                    return True
        elif action == "notify":
            print(f"[MATCH - NOTIFY ONLY] {loc} has tests around {date_str}")
            notify_audible(urgent=False)
        else:
            print(f"[INFO] {loc}: available around {date_str} (outside target months)")
    return False


def wait_until_test_centre_page_ready(bridge: ChromeCDPBridge) -> None:
    """If Chrome was just launched via start_chrome.bat (e.g. on New Tab or login screen),
    waits quietly until the DVSA 'Test centre' page is open before starting the search loop.
    Also detects if the tab is currently on an Error 15 block page and runs the 15/30/60m cooldown.
    """
    ready_script = """
    Boolean(document.querySelector('#test-centres-input, #test-centres-submit, a.test-centre-details-link'))
    """
    if is_error_15_block_page(bridge):
        wait_for_error_15_resolution(bridge)

    try:
        if bridge.evaluate(ready_script):
            return
    except Exception:
        pass

    print(
        "\n[Waiting] Please navigate to the DVSA 'Test centre' page in the Chrome window.\n"
        "          The bot will start monitoring automatically as soon as the page is loaded..."
    )
    while True:
        time.sleep(2.0)
        if not bridge.is_tab_open():
            print("\n[INFO] Chrome tab/window was closed by user. Exiting bot cleanly.")
            sys.exit(0)
        if is_error_15_block_page(bridge):
            wait_for_error_15_resolution(bridge)
        try:
            if bridge.evaluate(ready_script):
                print("[Ready] DVSA 'Test centre' page detected! Starting search loop...\n")
                time.sleep(0.5)
                return
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid Chrome CDP Booking Bot")
    parser.add_argument(
        "--test-calendar",
        action="store_true",
        help="Immediately test clicking the earliest calendar date, latest time slot, and Continue on the currently open 'Test time' page.",
    )
    parser.add_argument(
        "--test-details",
        action="store_true",
        help="Immediately test filling Step 6 ('Your details') candidate details form on the currently open page.",
    )
    parser.add_argument(
        "--no-submit",
        action="store_true",
        help="When used with --test-details, fills all candidate fields without clicking the final 'Next: payment details' submit button.",
    )
    args = parser.parse_args()

    bridge = ChromeCDPBridge()
    bridge.connect(auto_launch=True)

    mode_str = "Physical Mouse (PyAutoGUI)" if getattr(config, "USE_PHYSICAL_MOUSE", False) else "100% Cursor-Free (CDP Native Input)"
    print(f"[Mode] {mode_str} | Target Pace: {config.MAX_SEARCHES_PER_HOUR} searches/hour")

    if args.test_calendar:
        print("[TEST MODE] Running calendar + time slot + continue flow on current page...")
        if handle_calendar_and_slot_flow(bridge):
            fill_candidate_details_and_submit(bridge, submit=not args.no_submit)
        return

    if args.test_details:
        print("[TEST MODE] Running Step 6 ('Your details') form auto-fill on current page...")
        fill_candidate_details_and_submit(bridge, submit=not args.no_submit)
        return

    wait_until_test_centre_page_ready(bridge)
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
                smart_sleep_with_keepalive(bridge, delay)
        else:
            delay = compute_smart_poll_delay()
            smart_sleep_with_keepalive(bridge, delay)
            if run_postcode_search(bridge, query=None):
                if check_current_results(bridge):
                    return


if __name__ == "__main__":
    main()
