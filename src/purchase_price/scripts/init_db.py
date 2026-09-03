from purchase_price import models  # noqa: F401
from purchase_price.db import Base, engine


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("Database tables created.")


if __name__ == "__main__":
    main()
