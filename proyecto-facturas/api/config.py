"""Datos de conexión a MySQL (el contenedor de Docker).

Si no se define ninguna variable de entorno se usan estos valores,
que son los mismos del archivo docker-compose.yml.
"""
import os

DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "1234")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "3309")
DB_NAME = os.getenv("DB_NAME", "invoice_db")


def database_uri(db_name=None):
    """Arma la dirección que SQLAlchemy usa para conectarse."""
    return (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/"
        f"{db_name or DB_NAME}?charset=utf8mb4"
    )
