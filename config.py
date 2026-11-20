"""Configuration for the Hybrid Chrome CDP + PyAutoGUI UI Automation Case Study.

DISCLAIMER:
This code is an archived educational and technical research demonstration of hybrid
browser automation (Chrome DevTools Protocol viewport coordinate projection vs. OS input).
It is NOT intended for use against live DVSA infrastructure in violation of DVSA Terms of Use.
By default, `DRY_RUN = True` is enabled so that no live booking transitions are submitted.
"""

# Safe default: when True, logs matching slots or fills local HTML test snapshots
# without submitting live booking transitions.
DRY_RUN = True

# Chrome DevTools Protocol endpoint
CDP_HOST = "http://127.0.0.1:9222"

# Example search queries (postcodes or centre names) for demonstration
SEARCH_QUERIES = [
    "EH14 4AS",
]

# Example target locations to scan under "Your search results"
TARGET_LOCATIONS = [
    "Edinburgh (Currie)",
]

# Locations where ANY available date triggers the demo flow (for offline snapshot testing)
ACCEPT_ANY_DATE_LOCATIONS = []

# Months/Years for demonstration matching (MM, YYYY)
AUTO_BOOK_MONTHS = []

# Months/Years that trigger an audible notification only (MM, YYYY)
NOTIFY_ONLY_MONTHS = []

# Rate-limit & polling research parameters:
# Empirically observed Spring Web Flow session ceiling is ~40 searches (~50 state transitions/hr).
MAX_SEARCHES_PER_HOUR = 36
POLL_JITTER_SECONDS = 5.0  # Random +/- seconds added to each wait interval
SEARCH_LIMIT_COOLDOWN_SECONDS = 300  # 5-minute cooldown probe when "Search limit reached" appears

# Cumulative retry milestones (in minutes) when Imperva Error 15 temporary cooldown occurs
ERROR_15_RETRY_MINUTES = [15, 30, 60]
SEARCH_LIMIT_LOG_FILE = "search_limit_log.jsonl"
AUTO_ADAPT_PACE_ON_LIMIT = False

PAGE_TRANSITION_DELAY = 1.5
ELEMENT_WAIT_TIMEOUT = 15.0  # Max seconds to wait for calendar / slots / buttons to load
CLICK_JITTER_PX = 3

# Input mode:
# False = 100% Cursor-Free mode via Chrome DevTools Protocol (never touches OS mouse/focus)
# True  = Physical OS mouse movement & clicks via PyAutoGUI
USE_PHYSICAL_MOUSE = False

# PyAutoGUI settings (only used when USE_PHYSICAL_MOUSE = True)
MOUSE_MOVE_DURATION = 0.25  # Smooth human-like movement duration
