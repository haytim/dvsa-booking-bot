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
    "Edinburgh (Musselburgh)",
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

# Polling / timing settings (in seconds)
POLL_INTERVAL_SECONDS = 4.0
PAGE_TRANSITION_DELAY = 1.5
ELEMENT_WAIT_TIMEOUT = 15.0  # Max seconds to wait for calendar / slots / buttons to load
CLICK_JITTER_PX = 3

# PyAutoGUI settings
MOUSE_MOVE_DURATION = 0.25  # Smooth human-like movement duration
