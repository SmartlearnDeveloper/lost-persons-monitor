import time
import argparse
import os
from pathlib import Path
import sys
from sqlalchemy import create_engine, text, Column, Integer, String, Date, DateTime, Enum, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from mysql.connector import errors as mysql_errors
import datetime
import enum

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config_loader import build_database_url, build_root_admin_url, get_db_settings

DB_SETTINGS = get_db_settings()

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

class CaseStatusEnum(enum.Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"

class Case(Base):
    __tablename__ = 'case_cases'
    case_id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey('persons_lost.person_id'), nullable=False, unique=True)
    status = Column(Enum(CaseStatusEnum), nullable=False, default=CaseStatusEnum.NEW)
    priority = Column(String(50))
    reported_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    resolved_at = Column(DateTime)
    resolution_summary = Column(String(1000))
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    is_priority = Column(Boolean, default=False)

    person = relationship("PersonLost", backref="case", uselist=False)
    actions = relationship("CaseAction", cascade="all, delete-orphan", back_populates="case")
    responsibles = relationship(
        "CaseResponsibleHistory",
        cascade="all, delete-orphan",
        back_populates="case",
        order_by="CaseResponsibleHistory.assigned_at.desc()",
    )

class CaseAction(Base):
    __tablename__ = 'case_actions'
    action_id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey('case_cases.case_id'), nullable=False)
    action_type = Column(String(100), nullable=False)
    notes = Column(String(2000))
    actor = Column(String(200))
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    metadata_json = Column(String(2000))

    case = relationship("Case", back_populates="actions")


class CaseResponsibleHistory(Base):
    __tablename__ = 'case_responsible_history'
    assignment_id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey('case_cases.case_id'), nullable=False)
    responsible_name = Column(String(200), nullable=False)
    assigned_by = Column(String(200))
    notes = Column(String(1000))
    assigned_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    case = relationship("Case", back_populates="responsibles")

def init_db(reset_database: bool = False):
    """
    Inicializa la base de datos y crea las tablas si no existen.
    Intenta conectarse varias veces antes de fallar.
    """
    # Conexión sin especificar la base de datos para poder crearla
    engine_admin = create_engine(build_root_admin_url())

    max_retries = 10
    retries = 0
    while retries < max_retries:
        try:
            with engine_admin.connect() as connection:
                if reset_database:
                    connection.execute(text(f"DROP DATABASE IF EXISTS {DB_SETTINGS['name']}"))
                    print(f"Base de datos '{DB_SETTINGS['name']}' eliminada.")
                connection.execute(text(f"CREATE DATABASE IF NOT EXISTS {DB_SETTINGS['name']}"))
                print(f"Base de datos '{DB_SETTINGS['name']}' asegurada.")
            break
        except (OperationalError, SQLAlchemyError, mysql_errors.Error) as e:
            print(f"Error de conexión a MySQL: {e}. Reintentando en 5 segundos...")
            retries += 1
            time.sleep(5)
    
    if retries == max_retries:
        print("No se pudo conectar a MySQL después de varios intentos. Abortando.")
        return

    # Conexión a la base de datos específica para crear las tablas
    engine = create_engine(build_database_url())
    
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
    parser = argparse.ArgumentParser(description="Inicializa o reinicia la base de datos del sistema.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Elimina la base de datos antes de recrearla (deja todo en blanco).",
    )
    args = parser.parse_args()
    reset_flag = args.reset or os.getenv("RESET_DB", "").lower() in {"1", "true", "yes"}
    print("Iniciando script de preparación de la base de datos...")
    init_db(reset_database=reset_flag)
