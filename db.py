"""Instancia única de SQLAlchemy, importada por el resto de los módulos."""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
