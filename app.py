import eventlet
eventlet.monkey_patch()

import os
import cloudinary
import cloudinary.uploader
from flask import Flask, render_template, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'pentagon_absolute_secret')

# Налаштування Cloudinary (дані візьмемо з Environment Variables на Render)
cloudinary.config(
  cloud_name = os.environ.get('CLOUDINARY_NAME'),
  api_key = os.environ.get('CLOUDINARY_KEY'),
  api_secret = os.environ.get('CLOUDINARY_SECRET')
)

database_url = os.environ.get('DATABASE_URL', 'sqlite:///chat_final.db')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- МОДЕЛІ ДАНИХ ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False) # @tag
    nickname = db.Column(db.String(50), nullable=False) # Ім'я, яке бачать всі
    password_hash = db.Column(db.String(255), nullable=False)
    color = db.Column(db.String(20), default='#5bc0de')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(50), nullable=False) # username відправника
    recipient = db.Column(db.String(50), nullable=True) # None = Глобал чат
    text = db.Column(db.String(1000), nullable=True)
    file_url = db.Column(db.String(500), nullable=True)
    msg_type = db.Column(db.String(20), default='text') # text або image
    color = db.Column(db.String(20)) # Колір ніка відправника

with app.app_context():
    db.create_all()

# --- API РОУТИ ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files['file']
    upload_result = cloudinary.uploader.upload(file)
    return jsonify({"url": upload_result['secure_url']}), 200

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"error": "Цей username вже зайнятий!"}), 400
    
    new_user = User(
        username=data['username'],
        nickname=data.get('nickname', data['username']),
        password_hash=generate_password_hash(data['password']),
        color=data.get('color', '#5bc0de')
    )
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"status": "success"}), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if user and check_password_hash(user.password_hash, data['password']):
        return jsonify({
            "username": user.username,
            "nickname": user.nickname,
            "color": user.color
        }), 200
    return jsonify({"error": "Невірний логін або пароль"}), 401

@app.route('/api/update_profile', methods=['POST'])
def update_profile():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if user:
        user.nickname = data.get('nickname', user.nickname)
        user.color = data.get('color', user.color)
        db.session.commit()
        return jsonify({"status": "success"}), 200
    return jsonify({"error": "User not found"}), 404

@app.route('/api/messages', methods=['GET'])
def get_messages():
    user = request.args.get('user')
    other = request.args.get('other') # "global" або username співрозмовника

    if other == "global":
        msgs = Message.query.filter_by(recipient=None).order_by(Message.id.asc()).all()
    else:
        msgs = Message.query.filter(
            ((Message.sender == user) & (Message.recipient == other)) |
            ((Message.sender == other) & (Message.recipient == user))
        ).order_by(Message.id.asc()).all()
    
    return jsonify([{
        "sender": m.sender,
        "text": m.text,
        "type": m.msg_type,
        "file": m.file_url,
        "color": m.color
    } for m in msgs])

# --- SOCKETS ---

connected_users = {}

@socketio.on('join')
def on_join(data):
    connected_users[data['username']] = request.sid
    emit('update_online', list(connected_users.keys()), broadcast=True)

@socketio.on('send_msg')
def handle_msg(data):
    msg = Message(
        sender=data['sender'],
        recipient=data.get('recipient'),
        text=data.get('text'),
        msg_type=data.get('type', 'text'),
        file_url=data.get('file'),
        color=data['color']
    )
    db.session.add(msg)
    db.session.commit()

    if msg.recipient:
        if msg.recipient in connected_users:
            emit('new_msg', data, to=connected_users[msg.recipient])
        emit('new_msg', data, to=request.sid)
    else:
        emit('new_msg', data, broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    for user, sid in list(connected_users.items()):
        if sid == request.sid:
            del connected_users[user]
            emit('update_online', list(connected_users.keys()), broadcast=True)
            break

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
