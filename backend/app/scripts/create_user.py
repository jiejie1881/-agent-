import argparse
from getpass import getpass

from app.domain.enums import UserRole
from app.infrastructure.database.session import SessionLocal
from app.services.auth_service import AuthService


def main() -> None:
    parser = argparse.ArgumentParser(description="创建系统登录用户")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", required=True, choices=[role.value for role in UserRole])
    args = parser.parse_args()
    password = getpass("Password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("两次输入的密码不一致")
    with SessionLocal() as session:
        user = AuthService(session).create_user(
            args.username, password, UserRole(args.role)
        )
    print(f"Created user {user.username} ({user.role.value})")


if __name__ == "__main__":
    main()
