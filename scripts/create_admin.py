"""One-time CLI to bootstrap the first admin account.

Deliberately not auto-seeded by the app itself -- shipping a hardcoded
default admin/password would be a known-credential security hole. Run
this once after setting up the database:

    python scripts/create_admin.py <username> <password> "<Display Name>"
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agents.users_store import create_user, get_user_by_username


def main():
    if len(sys.argv) != 4:
        print('Usage: python scripts/create_admin.py <username> <password> "<Display Name>"')
        sys.exit(1)

    username, password, display_name = sys.argv[1], sys.argv[2], sys.argv[3]

    if get_user_by_username(username):
        print(f"User {username!r} already exists.")
        sys.exit(1)

    user = create_user(username, password, display_name, role="admin")
    print(f"Created admin user {user['username']!r} (id={user['id']}). Log in at /login.")


if __name__ == "__main__":
    main()
