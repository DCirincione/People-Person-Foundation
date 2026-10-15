"""Homepage content. Replace pending entries as the team details arrive."""

TEAM = [
    {"name": "Joe Aiello", "role": "President", "image": None},
    *[{"name": "Team member", "role": "Details coming soon", "image": None} for _ in range(8)],
]

# Set these to the real destinations when available.
EMAIL_SIGNUP_URL = None
DONATE_URL = None
CONTACT_EMAIL = "peoplepersonfoundation@gmail.com"

CONTACT_PHONE = "(631) 905-9595"
INSTAGRAM_URL = "https://www.instagram.com/peoplepersonfoundation/"
