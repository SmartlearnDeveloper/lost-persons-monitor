import os
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# --- Cargar configuración de forma robusta ---
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, '..', 'config.json')

with open(config_path, 'r') as f:
    config = json.load(f)

DATABASE_URL = (
    f"mysql+mysqlconnector://{config['db_user']}:{config['db_password']}@"
    f"{config['db_host']}:{config['db_port']}/{config['db_name']}"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()