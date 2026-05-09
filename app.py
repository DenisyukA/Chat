# ЦІ ДВА РЯДКИ ЗАВЖДИ ПЕРШІ
import eventlet
eventlet.monkey_patch()

import os
from flask import Flask, render_template, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# --- РОБОТА ЗІ ЗМІННИМИ ОТОЧЕННЯ ---
# Якщо ми локально - беремо стандартний ключ, якщо на Render - беремо з налаштувань
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'pentagon_absolute_secret')

# Отримуємо посилання на базу з налаштувань Render. 
# Якщо змінної немає (наприклад, ти запускаєш локально), створюється тестовий файл sqlite
database_url = os.environ.get('DATABASE_URL', 'sqlite:///local_test.db')

# Автоматичний фікс префікса для SQLAlchemy (Render/Neon часто дають postgres://)
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app)
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Словник для відстеження онлайн-юзерів
connected_users = {}

# --- СТРУКТУРА БАЗИ ДАНИХ ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    color = db.Column(db.String(20), nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(20), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    recipient = db.Column(db.String(50), nullable=True)

# Створюємо таблиці при запуску
with app.app_context():
    db.create_all()


# --- HTTP РОУТИ (АВТОРИЗАЦІЯ ТА ІСТОРІЯ) ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    
    # Перевіряємо, чи є вже такий юзер
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"error": "Позивний вже зайнятий!"}), 400

    # Шифруємо пароль
    hashed_pw = generate_password_hash(data['password'])
    
    new_user = User(
        username=data['username'], 
        password_hash=hashed_pw, 
        color=data.get('color', '#5bc0de')
    )
    db.session.add(new_user)
    db.session.commit()
    
    return jsonify({"status": "success"}), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    
    # Перевіряємо юзера та розшифровуємо пароль
    if user and check_password_hash(user.password_hash, data['password']):
        return jsonify({"status": "success", "color": user.color}), 200
        
    return jsonify({"error": "Невірний позивний або пароль"}), 401

@app.route('/api/messages', methods=['GET'])
def get_messages():
    current_user = request.args.get('user')
    
    # Дістаємо глобальні повідомлення + приватні для нас + приватні від нас
    messages = Message.query.filter(
        (Message.recipient == None) | 
        (Message.recipient == current_user) | 
        (Message.username == current_user)
    ).order_by(Message.id.asc()).all()
    
    result = [{"username": m.username, "color": m.color, "text": m.text, "recipient": m.recipient} for m in messages]
    return jsonify(result), 200


# --- WEBSOCKETS (ЧАТ) ---

@socketio.on('register_socket')
def handle_register(data):
    username = data['username']
    connected_users[username] = request.sid
    emit('update_users', list(connected_users.keys()), broadcast=True)

@socketio.on('send_message')
def handle_message(data):
    recipient = data.get('recipient')
    
    new_msg = Message(
        username=data['username'], 
        color=data['color'], 
        text=data['text'],
        recipient=recipient
    )
    db.session.add(new_msg)
    db.session.commit()
    
    # Маршрутизація
    if recipient:
        target_sid = connected_users.get(recipient)
        if target_sid:
            emit('receive_message', data, to=target_sid)
        # Відправляємо копію собі, щоб бачити власне повідомлення
        emit('receive_message', data, to=request.sid)
    else:
        emit('receive_message', data, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    for user, sid in list(connected_users.items()):
        if sid == request.sid:
            del connected_users[user]
            emit('update_users', list(connected_users.keys()), broadcast=True)
            break

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
