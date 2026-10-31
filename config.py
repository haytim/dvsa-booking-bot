"""Configuration for the Hybrid Chrome + PyAutoGUI Booking Bot."""

# Chrome DevTools Protocol endpoint
CDP_HOST = "http://127.0.0.1:9222"

# Search queries (postcodes or centre names) to cycle through using the
# "Search by your home postcode or by test centre name" input box.
# Leave empty [] if you only want to click "Find test centres" with whatever is already in the box.
SEARCH_QUERIES = [
    "DD1 4NN",
    "EH16 6BG",
]

# Target locations to scan under "Your search results"
TARGET_LOCATIONS = [
    "Dundee",
    "Arbroath",
    "Edinburgh (Musselburgh)",
    "Edinburgh (Currie)",
    "Livingston",
]

# Locations where ANY available date should immediately trigger auto-booking (for testing)
ACCEPT_ANY_DATE_LOCATIONS = []

# Months/Years that should trigger an automatic click & booking flow (MM, YYYY)
AUTO_BOOK_MONTHS = [
    (11, 2026),
    (12, 2026),
]

# Months/Years that should trigger an audible notification only (MM, YYYY)
NOTIFY_ONLY_MONTHS = [
    (1, 2027),
]

# Rate limit & polling settings:
# Pushing to 49 searches/hour (~1 search every 73s) to empirically test DVSA's rolling limit.
# When the "Search limit reached" modal appears, the bot logs the exact number of searches
# and execution state transitions (e1sXX) that triggered it, then probes recovery.
MAX_SEARCHES_PER_HOUR = 49
POLL_JITTER_SECONDS = 5.0  # Random +/- seconds added to each wait interval
SEARCH_LIMIT_COOLDOWN_SECONDS = 300  # 5-minute cooldown probe when "Search limit reached" appears
# Cumulative retry milestones (in minutes) when Imperva "Access Denied / Error 15" temporary block occurs:
# Waits until 15m elapsed -> retries -> waits until 30m elapsed -> retries -> waits until 60m elapsed -> retries
ERROR_15_RETRY_MINUTES = [15, 30, 60]
SEARCH_LIMIT_LOG_FILE = "search_limit_log.jsonl"  # Persistent log of rate-limit & failure events
AUTO_ADAPT_PACE_ON_LIMIT = False  # Set True to automatically lower MAX_SEARCHES_PER_HOUR after hitting the cap

PAGE_TRANSITION_DELAY = 1.5
ELEMENT_WAIT_TIMEOUT = 15.0  # Max seconds to wait for calendar / slots / buttons to load
CLICK_JITTER_PX = 3

# Input mode:
# False = 100% Cursor-Free mode via Chrome DevTools Protocol (never touches your OS mouse/focus)
# True  = Physical OS mouse movement & clicks via PyAutoGUI
USE_PHYSICAL_MOUSE = False

# PyAutoGUI settings (only used when USE_PHYSICAL_MOUSE = True)
MOUSE_MOVE_DURATION = 0.25  # Smooth human-like movement duration
