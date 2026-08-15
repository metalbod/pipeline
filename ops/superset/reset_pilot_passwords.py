"""One-off: resets the two Phase 3 pilot users' Superset passwords and prints them once.
Their original passwords were random (secrets.token_urlsafe) and never stored anywhere
retrievable -- this generates fresh ones the same way, for manual secure relay.

Invoke via: docker exec -i <superset-container> python /app/reset_pilot_passwords.py
"""

import secrets

from superset.app import create_app

USERNAMES = ["kenneth.yong@mandrill.com.my", "metalbod@gmail.com"]


def main():
    app = create_app()
    with app.app_context():
        sm = app.appbuilder.sm
        for username in USERNAMES:
            user = sm.find_user(username=username)
            if user is None:
                print(f"user not found: {username}")
                continue
            password = secrets.token_urlsafe(16)
            sm.reset_password(user.id, password)
            print(f"{username}: {password}")


if __name__ == "__main__":
    main()
