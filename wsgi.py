# wsgi.py
import sys
import os

# Добавляем путь к папке проекта
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Импортируем приложение
from server.main import app as application

# Инициализируем базу данных при запуске
from server.main import init_db
init_db()
