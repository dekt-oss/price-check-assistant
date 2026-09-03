from alembic.config import Config

from alembic import command


def main() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    print("Database migrations applied.")


if __name__ == "__main__":
    main()
