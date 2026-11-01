"""Read owner-entered metadata using the caller's current read transaction."""


def company_name_default(conn) -> str:
    """Return the owner's saved company name; never invent a display value."""
    try:
        row = conn.execute("SELECT company_name FROM owner_profile WHERE profile_id='owner'").fetchone()
    except Exception:
        return ''
    return str(row[0] or '').strip() if row else ''
