# server/main.py
import os
import sys
import json
import sqlite3
import hashlib
import secrets
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

from flask import Flask, request, jsonify, g
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Путь к базе данных
DB_PATH = os.path.join(os.path.dirname(__file__), "server_data", "painting_orders.db")

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def hash_password(password: str) -> str:
    """Хеширование пароля"""
    salt = secrets.token_hex(16)
    password_hash = hashlib.pbkdf2_hmac(
        'sha256', password.encode(), salt.encode(), 100000
    ).hex()
    return f"{salt}${password_hash}"

def verify_password(password: str, password_hash: str) -> bool:
    """Проверка пароля"""
    try:
        salt, hash_part = password_hash.split("$")
        computed_hash = hashlib.pbkdf2_hmac(
            'sha256', password.encode(), salt.encode(), 100000
        ).hex()
        return secrets.compare_digest(computed_hash, hash_part)
    except:
        return False

def generate_token() -> str:
    """Генерация токена сессии"""
    return secrets.token_urlsafe(32)

def execute_with_retry(func, max_retries=5, delay=0.1):
    """Выполняет функцию с повторными попытками при блокировке БД"""
    last_error = None
    for attempt in range(max_retries):
        try:
            return func()
        except sqlite3.OperationalError as e:
            last_error = e
            if "database is locked" in str(e) and attempt < max_retries - 1:
                time.sleep(delay * (attempt + 1))
                continue
            raise
    raise last_error

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

# ========== АУТЕНТИФИКАЦИЯ ==========
@app.route('/api/auth/login', methods=['POST'])
def login():
    """Вход в систему"""
    data = request.get_json()
    username = data.get('username', '')
    password = data.get('password', '')
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        return jsonify({"detail": "Неверный логин или пароль"}), 401
    
    if not verify_password(password, user['password_hash']):
        conn.close()
        return jsonify({"detail": "Неверный логин или пароль"}), 401
    
    if not user['is_active']:
        conn.close()
        return jsonify({"detail": "Аккаунт отключён"}), 403
    
    token = generate_token()
    expires_at = datetime.now() + timedelta(days=7)
    
    cursor.execute("""
        INSERT INTO sessions (token, user_id, expires_at)
        VALUES (?, ?, ?)
    """, (token, user['id'], expires_at.isoformat()))
    conn.commit()
    conn.close()
    
    return jsonify({
        "token": token,
        "user": {
            "id": user['id'],
            "username": user['username'],
            "full_name": user['full_name'],
            "role": user['role']
        }
    })

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Выход из системы"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    return jsonify({"message": "Выход выполнен"})

def get_current_user():
    """Получение текущего пользователя из заголовка Authorization"""
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    
    token = auth_header[7:]
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT u.id, u.username, u.full_name, u.role, u.is_active,
               s.expires_at
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token = ?
    """, (token,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    # Проверяем срок действия
    if row['expires_at']:
        try:
            expires_at = datetime.fromisoformat(row['expires_at'])
            if expires_at < datetime.now():
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
                conn.commit()
                conn.close()
                return None
        except:
            pass
    
    return {
        "id": row['id'],
        "username": row['username'],
        "full_name": row['full_name'],
        "role": row['role'],
        "is_active": row['is_active']
    }

# ========== API: ПОЛЬЗОВАТЕЛИ ==========
@app.route('/api/users', methods=['GET'])
def get_users():
    """Получить список пользователей (только admin)"""
    user = get_current_user()
    if not user or user['role'] != 'admin':
        return jsonify({"detail": "Недостаточно прав"}), 403
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, full_name, role, is_active, created_at FROM users ORDER BY username")
    users = cursor.fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

@app.route('/api/users', methods=['POST'])
def create_user():
    """Создать пользователя (только admin)"""
    user = get_current_user()
    if not user or user['role'] != 'admin':
        return jsonify({"detail": "Недостаточно прав"}), 403
    
    data = request.get_json()
    username = data.get('username', '')
    password = data.get('password', '')
    full_name = data.get('full_name', '')
    role = data.get('role', 'editor')
    
    if not username or not password:
        return jsonify({"detail": "Введите логин и пароль"}), 400
    
    if len(password) < 6:
        return jsonify({"detail": "Пароль должен содержать минимум 6 символов"}), 400
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE username = ?", (username,))
    if cursor.fetchone()[0] > 0:
        conn.close()
        return jsonify({"detail": "Пользователь с таким именем уже существует"}), 400
    
    password_hash = hash_password(password)
    cursor.execute("""
        INSERT INTO users (username, password_hash, full_name, role)
        VALUES (?, ?, ?, ?)
    """, (username, password_hash, full_name, role))
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({
        "id": user_id,
        "username": username,
        "full_name": full_name,
        "role": role,
        "is_active": True
    })

# ========== API: СПРАВОЧНИКИ ==========
@app.route('/api/profiles', methods=['GET'])
def get_profiles():
    """Получить все профили"""
    user = get_current_user()
    if not user:
        return jsonify({"detail": "Не авторизован"}), 401
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.name, c.name as category, p.height_mm, p.width_mm, 
               p.weight_kg_per_meter, p.stick_length_meters, p.image_path, 
               COALESCE(p.price, 0) as price, COALESCE(p.measure_type, 'meters') as measure_type,
               p.model_3d_path, p.uuid
        FROM profiles p 
        LEFT JOIN categories c ON p.category_id = c.id 
        ORDER BY c.name, p.name
    """)
    result = cursor.fetchall()
    conn.close()
    return jsonify([list(r) for r in result])

@app.route('/api/colors', methods=['GET'])
def get_colors():
    """Получить список цветов"""
    user = get_current_user()
    if not user:
        return jsonify({"detail": "Не авторизован"}), 401
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, code, category_id FROM colors ORDER BY name")
    result = cursor.fetchall()
    conn.close()
    return jsonify([list(r) for r in result])

@app.route('/api/contractors', methods=['GET'])
def get_contractors():
    """Получить список контрагентов"""
    user = get_current_user()
    if not user:
        return jsonify({"detail": "Не авторизован"}), 401
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, phone, email FROM contractors ORDER BY name")
    result = cursor.fetchall()
    conn.close()
    return jsonify([list(r) for r in result])

@app.route('/api/painters', methods=['GET'])
def get_painters():
    """Получить список покрасчиков"""
    user = get_current_user()
    if not user:
        return jsonify({"detail": "Не авторизован"}), 401
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, phone, address, COALESCE(max_paint_length_m, 3.0) 
        FROM painters ORDER BY name
    """)
    result = cursor.fetchall()
    conn.close()
    return jsonify([list(r) for r in result])

@app.route('/api/categories', methods=['GET'])
def get_categories():
    """Получить список категорий"""
    user = get_current_user()
    if not user:
        return jsonify({"detail": "Не авторизован"}), 401
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM categories ORDER BY name")
    result = cursor.fetchall()
    conn.close()
    return jsonify([list(r) for r in result])

# ========== API: ЗАКАЗЫ ==========
@app.route('/api/orders', methods=['GET'])
def get_orders():
    """Получить все заказы"""
    user = get_current_user()
    if not user:
        return jsonify({"detail": "Не авторизован"}), 401
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            h.id, h.order_number, h.created_at, 
            COALESCE(c.name, '') as contractor, h.workshop,
            COALESCE((SELECT COUNT(*) FROM order_items i WHERE i.order_id = h.id), 0) as positions,
            COALESCE((SELECT SUM(i.total_meters) FROM order_items i WHERE i.order_id = h.id AND i.measure_type = 'meters'), 0) as total_meters,
            COALESCE((SELECT SUM(i.total_weight) FROM order_items i WHERE i.order_id = h.id), 0) as total_weight,
            h.total_pages,
            h.locked_by,
            COALESCE(u.full_name, u.username, '') as locked_by_name,
            h.uuid
        FROM orders h
        LEFT JOIN contractors c ON h.contractor_id = c.id
        LEFT JOIN users u ON h.locked_by = u.id
        ORDER BY h.created_at DESC
    ''')
    result = cursor.fetchall()
    conn.close()
    return jsonify([list(r) for r in result])

@app.route('/api/orders/<int:order_id>', methods=['GET'])
def get_order(order_id):
    """Получить заявку по ID"""
    user = get_current_user()
    if not user:
        return jsonify({"detail": "Не авторизован"}), 401
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, order_number, contractor_id, workshop, painter_id, total_pages, 
               created_by, created_at, updated_at, version, locked_by, locked_at, uuid
        FROM orders WHERE id = ?
    """, (order_id,))
    order = cursor.fetchone()
    
    if not order:
        conn.close()
        return jsonify({"detail": "Заявка не найдена"}), 404
    
    cursor.execute("""
        SELECT id, page_number, profile_name, height_mm, width_mm, length_mm,
               quantity, color_name, total_meters, total_weight, comment, measure_type,
               is_defective, defective_id, defective_quantity, page_painter_id, current_status
        FROM order_items WHERE order_id = ?
        ORDER BY page_number, id
    """, (order_id,))
    items = cursor.fetchall()
    conn.close()
    
    return jsonify({
        "order": dict(order),
        "items": [dict(item) for item in items]
    })

# ========== API: СОХРАНЕНИЕ ЗАКАЗОВ ==========
@app.route('/api/orders/save', methods=['POST'])
def save_order():
    """Сохранить заявку"""
    user = get_current_user()
    if not user:
        return jsonify({"detail": "Не авторизован"}), 401
    
    data = request.get_json()
    order_id = data.get('order_id')  # Может быть None
    order_uuid = data.get('order_uuid')  # Может быть None
    order_number = data.get('order_number', '')
    contractor_id = data.get('contractor_id')
    workshop = data.get('workshop', 1)
    painter_id = data.get('painter_id')
    total_pages = data.get('total_pages', 1)
    items = data.get('items', [])
    user_id = data.get('user_id', user['id'])
    
    # ЕСЛИ НЕТ UUID - ГЕНЕРИРУЕМ НА СЕРВЕРЕ
    if not order_uuid:
        order_uuid = str(uuid.uuid4())
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        if order_id:
            # ОБНОВЛЕНИЕ СУЩЕСТВУЮЩЕЙ ЗАЯВКИ
            cursor.execute("SELECT version, uuid FROM orders WHERE id = ?", (order_id,))
            existing = cursor.fetchone()
            
            if existing:
                current_version = existing[0]
                new_version = current_version + 1
                db_uuid = existing[1] or order_uuid
                
                cursor.execute('''
                    UPDATE orders 
                    SET contractor_id = ?, workshop = ?, painter_id = ?, total_pages = ?,
                        updated_at = CURRENT_TIMESTAMP, version = ?, uuid = ?
                    WHERE id = ?
                ''', (contractor_id, workshop, painter_id, total_pages, new_version, db_uuid, order_id))
                
                cursor.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
                
                for item in items:
                    cursor.execute('''
                        INSERT INTO order_items (order_id, page_number, profile_name, height_mm, width_mm, length_mm,
                                                 quantity, color_name, total_meters, total_weight, comment, measure_type,
                                                 is_defective, defective_id, defective_quantity, page_painter_id, current_status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (order_id, item.get('page_number', 1), item.get('profile_name', ''),
                          item.get('height_mm', 0), item.get('width_mm', 0), item.get('length_mm', 0),
                          item.get('quantity', 1), item.get('color_name', ''), item.get('total_meters', 0),
                          item.get('total_weight', 0), item.get('comment', ''), item.get('measure_type', 'meters'),
                          item.get('is_defective', 0), item.get('defective_id'), item.get('defective_quantity', 0),
                          item.get('page_painter_id'), item.get('current_status', 'Новая')))
                
                # Создаём новую версию
                order_data = {
                    "order_id": order_id,
                    "order_uuid": db_uuid,
                    "order_number": order_number,
                    "contractor_id": contractor_id,
                    "workshop": workshop,
                    "painter_id": painter_id,
                    "total_pages": total_pages,
                    "items": items
                }
                cursor.execute('''
                    INSERT INTO order_versions (order_id, version_number, data, changed_by)
                    VALUES (?, ?, ?, ?)
                ''', (order_id, new_version, json.dumps(order_data, ensure_ascii=False), user_id))
                
                cursor.execute("UPDATE orders SET locked_by = NULL, locked_at = NULL WHERE id = ?", (order_id,))
                
                conn.commit()
                conn.close()
                
                return jsonify({"message": "Заявка обновлена", "order_id": order_id, "version": new_version, "uuid": db_uuid})
        
        else:
            # СОЗДАНИЕ НОВОЙ ЗАЯВКИ
            cursor.execute('''
                INSERT INTO orders (uuid, order_number, contractor_id, workshop, painter_id, total_pages, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (order_uuid, order_number, contractor_id, workshop, painter_id, total_pages, user_id))
            
            new_order_id = cursor.lastrowid
            
            for item in items:
                cursor.execute('''
                    INSERT INTO order_items (order_id, page_number, profile_name, height_mm, width_mm, length_mm,
                                             quantity, color_name, total_meters, total_weight, comment, measure_type,
                                             is_defective, defective_id, defective_quantity, page_painter_id, current_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (new_order_id, item.get('page_number', 1), item.get('profile_name', ''),
                      item.get('height_mm', 0), item.get('width_mm', 0), item.get('length_mm', 0),
                      item.get('quantity', 1), item.get('color_name', ''), item.get('total_meters', 0),
                      item.get('total_weight', 0), item.get('comment', ''), item.get('measure_type', 'meters'),
                      item.get('is_defective', 0), item.get('defective_id'), item.get('defective_quantity', 0),
                      item.get('page_painter_id'), item.get('current_status', 'Новая')))
            
            # Создаём первую версию
            order_data = {
                "order_id": new_order_id,
                "order_uuid": order_uuid,
                "order_number": order_number,
                "contractor_id": contractor_id,
                "workshop": workshop,
                "painter_id": painter_id,
                "total_pages": total_pages,
                "items": items
            }
            cursor.execute('''
                INSERT INTO order_versions (order_id, version_number, data, changed_by)
                VALUES (?, ?, ?, ?)
            ''', (new_order_id, 1, json.dumps(order_data, ensure_ascii=False), user_id))
            
            conn.commit()
            conn.close()
            
            return jsonify({"message": "Заявка создана", "order_id": new_order_id, "version": 1, "uuid": order_uuid})
    
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Ошибка сохранения заказа: {e}")
        return jsonify({"detail": str(e)}), 500

# ========== API: БЛОКИРОВКИ ==========
@app.route('/api/orders/<int:order_id>/lock', methods=['POST'])
def lock_order(order_id):
    """Заблокировать заявку"""
    user = get_current_user()
    if not user:
        return jsonify({"detail": "Не авторизован"}), 401
    
    data = request.get_json()
    user_id = data.get('user_id', user['id'])
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT locked_by FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()
    
    if not order:
        conn.close()
        return jsonify({"detail": "Заявка не найдена"}), 404
    
    if order['locked_by']:
        conn.close()
        return jsonify({"detail": "Заявка уже заблокирована"}), 409
    
    cursor.execute("""
        UPDATE orders SET locked_by = ?, locked_at = CURRENT_TIMESTAMP WHERE id = ?
    """, (user_id, order_id))
    conn.commit()
    conn.close()
    
    return jsonify({"message": "Заявка заблокирована"})

@app.route('/api/orders/<int:order_id>/unlock', methods=['POST'])
def unlock_order(order_id):
    """Разблокировать заявку"""
    user = get_current_user()
    if not user:
        return jsonify({"detail": "Не авторизован"}), 401
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT locked_by FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()
    
    if not order:
        conn.close()
        return jsonify({"detail": "Заявка не найдена"}), 404
    
    if order['locked_by'] and order['locked_by'] != user['id'] and user['role'] != 'admin':
        conn.close()
        return jsonify({"detail": "Вы не можете разблокировать заявку"}), 403
    
    cursor.execute("UPDATE orders SET locked_by = NULL, locked_at = NULL WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    
    return jsonify({"message": "Заявка разблокирована"})

# ========== ГЛАВНЫЙ ЭНДПОИНТ ==========
@app.route('/')
def index():
    """Проверка работы сервера"""
    return jsonify({
        "message": "PaintingOrders Server API",
        "status": "running",
        "version": "1.0"
    })

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    init_db()
    print("Сервер запущен")
    app.run(host='0.0.0.0', port=8000, debug=True)

# Инициализация базы данных при импорте (для gunicorn)
init_db()
