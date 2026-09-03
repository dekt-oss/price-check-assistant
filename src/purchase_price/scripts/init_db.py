from alembic import command
from alembic.config import Config


def main() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    print("Database migrations applied.")


if __name__ == "__main__":
    main()
