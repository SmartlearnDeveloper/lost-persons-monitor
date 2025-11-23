import time
import argparse
import os
import random
from pathlib import Path
import sys
import datetime
import enum
from sqlalchemy import create_engine, text, Column, Integer, String, Date, DateTime, Enum, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, relationship, Session
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from mysql.connector import errors as mysql_errors
from passlib.context import CryptContext

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config_loader import build_database_url, build_root_admin_url, get_db_settings

DB_SETTINGS = get_db_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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
    created_by = Column(Integer, ForeignKey('auth_users.user_id'), nullable=True)

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
    responsible_name = Column(String(200))
    created_by = Column(Integer, ForeignKey('auth_users.user_id'), nullable=True)
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


class ResponsibleContact(Base):
    __tablename__ = 'responsible_contacts'
    contact_id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(200), nullable=False)
    role = Column(String(200), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class AuthUser(Base):
    __tablename__ = 'auth_users'
    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False)
    full_name = Column(String(150))
    email = Column(String(150))
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class AuthRole(Base):
    __tablename__ = 'auth_roles'
    role_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255))


class AuthPermission(Base):
    __tablename__ = 'auth_permissions'
    permission_id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(100), unique=True, nullable=False)
    description = Column(String(255))


class AuthRolePermission(Base):
    __tablename__ = 'auth_role_permissions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(Integer, ForeignKey('auth_roles.role_id'), nullable=False)
    permission_id = Column(Integer, ForeignKey('auth_permissions.permission_id'), nullable=False)


class AuthUserRole(Base):
    __tablename__ = 'auth_user_roles'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('auth_users.user_id'), nullable=False)
    role_id = Column(Integer, ForeignKey('auth_roles.role_id'), nullable=False)

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
        return

    _seed_auth_data(engine)
    _seed_responsible_contacts(engine)


def _seed_responsible_contacts(engine) -> None:
    roles = [
        "Coordinador General",
        "Líder Zona Norte",
        "Líder Zona Centro",
        "Líder Zona Sur",
        "Supervisor de Campo",
        "Analista de Operaciones",
    ]
    first_names = ["Ana", "Bruno", "Camila", "Daniel", "Elena", "Fabio", "Gabriela", "Hugo", "Iván", "Julia"]
    last_names = ["Ríos", "Serrano", "López", "Medina", "Paz", "Izurieta", "Cárdenas", "Delgado", "Salazar", "Morales"]
    with Session(engine) as session:
        if session.query(ResponsibleContact).count() > 0:
            return
        random.seed(42)
        contacts = []
        for role in roles:
            name = f"{random.choice(first_names)} {random.choice(last_names)}"
            contacts.append(ResponsibleContact(full_name=name, role=role))
        session.add_all(contacts)
        session.commit()


def _seed_auth_data(engine) -> None:
    permissions = [
        ("report", "Registrar personas perdidas"),
        ("dashboard", "Ver dashboard y estadísticas"),
        ("pdf_reports", "Generar reportes PDF"),
        ("case_manager", "Gestionar casos y responsables"),
        ("manage_users", "Administrar usuarios y roles"),
    ]
    roles = [
        ("reporter", ["report", "dashboard"]),
        ("analyst", ["report", "dashboard", "pdf_reports"]),
        ("coordinator", ["report", "dashboard", "pdf_reports", "case_manager"]),
        ("admin", ["report", "dashboard", "pdf_reports", "case_manager", "manage_users"]),
    ]
    default_admin = {
        "username": os.getenv("AUTH_DEFAULT_ADMIN_USERNAME", "admin"),
        "password": os.getenv("AUTH_DEFAULT_ADMIN_PASSWORD", "admin123"),
        "full_name": "Administrador",
        "email": "admin@example.com",
    }
    with Session(engine) as session:
        existing_perms = {p.code for p in session.query(AuthPermission).all()}
        for code, desc in permissions:
            if code not in existing_perms:
                session.add(AuthPermission(code=code, description=desc))
        session.commit()

        perm_map = {p.code: p.permission_id for p in session.query(AuthPermission).all()}

        role_entities = {r.name: r for r in session.query(AuthRole).all()}
        for role_name, _ in roles:
            if role_name not in role_entities:
                role = AuthRole(name=role_name, description=f"Rol {role_name}")
                session.add(role)
                session.commit()
                role_entities[role_name] = role

        existing_rp = session.query(AuthRolePermission).all()
        rp_set = {(rp.role_id, rp.permission_id) for rp in existing_rp}
        for role_name, perm_codes in roles:
            role = role_entities[role_name]
            for code in perm_codes:
                perm_id = perm_map.get(code)
                if perm_id is None:
                    continue
                if (role.role_id, perm_id) not in rp_set:
                    session.add(AuthRolePermission(role_id=role.role_id, permission_id=perm_id))
        session.commit()

        admin_user = session.query(AuthUser).filter(AuthUser.username == default_admin["username"]).first()
        if not admin_user:
            hashed = pwd_context.hash(default_admin["password"])
            admin_user = AuthUser(
                username=default_admin["username"],
                full_name=default_admin["full_name"],
                email=default_admin["email"],
                hashed_password=hashed,
            )
            session.add(admin_user)
            session.commit()

        admin_role = role_entities["admin"]
        existing_ur = session.query(AuthUserRole).filter(
            AuthUserRole.user_id == admin_user.user_id,
            AuthUserRole.role_id == admin_role.role_id,
        ).first()
        if not existing_ur:
            session.add(AuthUserRole(user_id=admin_user.user_id, role_id=admin_role.role_id))
            session.commit()

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
