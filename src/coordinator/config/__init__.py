import os

POSTGRES_USER = os.environ.get("POSTGRES_USER") or "task_rw"
POSTGRES_HOST = os.environ.get("POSTGRES_HOST") or "localhost"
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD") or "task123"
POSTGRES_DB = os.environ.get("POSTGRES_DB") or "tasks"
POSTGRES_PORT = os.environ.get("POSTGRES_PORT") or 5432
SQLALCHEMY_DATABASE_URI = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)
