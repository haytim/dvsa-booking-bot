"""Example template for Step 6 ('Your details') candidate form demonstration.

For offline HTML snapshot testing (`python bot.py --test-details --no-submit`),
copy this file to `candidate_details.py` (which is git-ignored) with dummy test data.
"""

CANDIDATE_DETAILS = {
    "title": "Mr",
    "first_names": "John",
    "surname": "Doe",
    "address_line_1": "10 Example Street",
    "address_line_2": "",
    "town": "Edinburgh",
    "postcode": "EH14 4AS",
    "email": "john.doe@example.com",
    "confirm_email": "john.doe@example.com",
    "contact_number": "07700900000",
}
