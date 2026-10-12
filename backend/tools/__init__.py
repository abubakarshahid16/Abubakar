"""Command-line, scoring and pilot tools (#725 F8a, #736).

NOT part of the app: nothing the server runs imports these, and
`scripts/check_unused_modules.py` keeps `backend/app` to what it does. They
import the app (`from app import ...`); the app never imports them.
"""
