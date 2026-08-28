# server/main.py
import os
import sys
import json
import sqlite3
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# Путь к базе данных
DB_PATH = os.path.join(os.path.dirname(__file__), "server_data", "painting_orders.db")

# ========== ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ПРИ ЗАПУСКЕ ==========
def init_db():
    """Создаёт таблицы в SQLite"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT DEFAULT '',
            role TEXT DEFAULT 'editor',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица сессий
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )
    ''')
    
    # Таблица заявок
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT,
            order_number TEXT UNIQUE NOT NULL,
            contractor_id INTEGER,
            workshop INTEGER DEFAULT 1,
            painter_id INTEGER,
            total_pages INTEGER DEFAULT 1,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            version INTEGER DEFAULT 1,
            locked_by INTEGER,
            locked_at TIMESTAMP
        )
    ''')
    
    # Таблица позиций заявки
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            page_number INTEGER DEFAULT 1,
            profile_name TEXT NOT NULL,
            height_mm REAL DEFAULT 0,
            width_mm REAL DEFAULT 0,
            length_mm REAL DEFAULT 0,
            quantity INTEGER DEFAULT 1,
            color_name TEXT NOT NULL,
            total_meters REAL DEFAULT 0,
            total_weight REAL DEFAULT 0,
            comment TEXT DEFAULT '',
            measure_type TEXT DEFAULT 'meters',
            is_defective INTEGER DEFAULT 0,
            defective_id INTEGER,
            defective_quantity INTEGER DEFAULT 0,
            page_painter_id INTEGER,
            current_status TEXT DEFAULT 'Новая'
        )
    ''')
    
    # Таблица версий заявок
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS order_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            data TEXT NOT NULL,
            changed_by INTEGER,
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            change_description TEXT DEFAULT ''
        )
    ''')
    
    # Таблица справочников: профили
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            category_id INTEGER,
            height_mm REAL DEFAULT 0,
            width_mm REAL DEFAULT 0,
            weight_kg_per_meter REAL DEFAULT 0.5,
            stick_length_meters REAL DEFAULT 6.0,
            image_path TEXT,
            price REAL DEFAULT 0,
            measure_type TEXT DEFAULT 'meters',
            model_3d_path TEXT,
            uuid TEXT
        )
    ''')
    
    # Таблица справочников: цвета
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS colors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            code TEXT,
            category_id INTEGER
        )
    ''')
    
    # Таблица справочников: категории цветов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS color_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    
    # Таблица справочников: контрагенты
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contractors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            phone TEXT,
            email TEXT
        )
    ''')
    
    # Таблица справочников: покрасчики
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS painters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            phone TEXT,
            address TEXT,
            max_paint_length_m REAL DEFAULT 3.0
        )
    ''')
    
    # Таблица справочников: категории
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    
    # Таблица для статусов позиций
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS order_item_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            changed_by TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            FOREIGN KEY (item_id) REFERENCES order_items(id) ON DELETE CASCADE
        )
    ''')
    
    # Таблица брака
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS defective_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT NOT NULL,
            profile_name TEXT NOT NULL,
            length_mm REAL NOT NULL,
            color_name TEXT NOT NULL,
            quantity INTEGER DEFAULT 1,
            used_quantity INTEGER DEFAULT 0,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            comment TEXT DEFAULT ''
        )
    ''')
    
    # Создаём администратора по умолчанию
    cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
    if cursor.fetchone()[0] == 0:
        password_hash = hash_password("admin123")
        cursor.execute(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
            ("admin", password_hash, "Администратор", "admin")
        )
    
    conn.commit()
    conn.close()
    print(f"База данных SQLite инициализирована: {DB_PATH}")

# ВЫЗЫВАЕМ ИНИЦИАЛИЗАЦИЮ ПРИ ИМПОРТЕ
init_db()

# ========== ОСТАЛЬНОЙ КОД (login, logout, get_profiles и т.д.) ==========
# ... (весь остальной код, который вы уже загрузили)
