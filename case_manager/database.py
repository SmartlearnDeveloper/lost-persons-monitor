from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config_loader import build_database_url

DATABASE_URL = build_database_url()

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
