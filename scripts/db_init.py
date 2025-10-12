import os
import json
import time
from sqlalchemy import create_engine, text, Column, Integer, String, Date, DateTime, Enum, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from mysql.connector import errors as mysql_errors
import datetime

# --- Cargar configuración de forma robusta ---
# Construye la ruta al archivo de configuración relativa a la ubicación de este script
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, '..', 'config.json')

with open(config_path, 'r') as f:
    config = json.load(f)

DB_USER = config['db_user']
DB_PASSWORD = config['db_password']
DB_HOST = config['db_host']
DB_PORT = config['db_port']
DB_NAME = config['db_name']

# --- Definición del ORM con SQLAlchemy ---
Base = declarative_base()

class PersonLost(Base):
    __tablename__ = 'persons_lost'
    person_id = Column(Integer, primary_key=True, autoincrement=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    gender = Column(Enum('M', 'F', 'O', name='gender_enum'), nullable=False)
    birth_date = Column(Date, nullable=False)
    age = Column(Integer)
    lost_timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    lost_location = Column(String(255))
    details = Column(String(1000))
    status = Column(Enum('active', 'found', 'cancelled', name='status_enum'), default='active')

class Reporter(Base):
    __tablename__ = 'reporters'
    reporter_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    contact_info = Column(String(200))

class PersonReporter(Base):
    __tablename__ = 'person_reporter'
    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey('persons_lost.person_id'))
    reporter_id = Column(Integer, ForeignKey('reporters.reporter_id'))
    relation = Column(String(100))
    person = relationship("PersonLost")
    reporter = relationship("Reporter")

# --- Tablas de Agregación para Flink ---
class AggAgeGroup(Base):
    __tablename__ = 'agg_age_group'
    age_group = Column(String(20), primary_key=True)
    count = Column(Integer)

class AggGender(Base):
    __tablename__ = 'agg_gender'
    gender = Column(String(1), primary_key=True)
    count = Column(Integer)

class AggHourly(Base):
    __tablename__ = 'agg_hourly'
    hour_of_day = Column(Integer, primary_key=True)
    count = Column(Integer)

def init_db():
    """
    Inicializa la base de datos y crea las tablas si no existen.
    Intenta conectarse varias veces antes de fallar.
    """
    # Conexión sin especificar la base de datos para poder crearla
    engine_admin_url = f"mysql+mysqlconnector://root:rootpassword@{DB_HOST}:{DB_PORT}"
    engine_admin = create_engine(engine_admin_url)

    max_retries = 10
    retries = 0
    while retries < max_retries:
        try:
            with engine_admin.connect() as connection:
                connection.execute(text(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}"))
                print(f"Base de datos '{DB_NAME}' asegurada.")
            break
        except (OperationalError, SQLAlchemyError, mysql_errors.Error) as e:
            print(f"Error de conexión a MySQL: {e}. Reintentando en 5 segundos...")
            retries += 1
            time.sleep(5)
    
    if retries == max_retries:
        print("No se pudo conectar a MySQL después de varios intentos. Abortando.")
        return

    # Conexión a la base de datos específica para crear las tablas
    db_url = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    engine = create_engine(db_url)
    
    print("Creando tablas en la base de datos...")
    retries = 0
    while retries < max_retries:
        try:
            Base.metadata.create_all(engine)
            print("Tablas creadas exitosamente.")
            break
        except (OperationalError, SQLAlchemyError, mysql_errors.Error) as e:
            print(f"Error creando tablas: {e}. Reintentando en 5 segundos...")
            retries += 1
            time.sleep(5)

    if retries == max_retries:
        print("No se pudieron crear las tablas después de varios intentos. Abortando.")

if __name__ == "__main__":
    print("Iniciando script de preparación de la base de datos...")
    init_db()
