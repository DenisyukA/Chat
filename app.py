from flask import Flask, render_template, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from flask_cors import CORS

app = Flask(__name__)
app.config['SECRET_KEY'] = 'pentagon_secret_key'

# ЗВЕРНИ УВАГУ: Назва бази тепер test_db_v2
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://neondb_owner:npg_5ZzaYxV4bSef@ep-noisy-mountain-alit1wnp.c-3.eu-central-1.aws.neon.tech/neondb?sslmode=require'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app)
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Словник для відстеження: {'Артем': 'унікальний_ID_сокета'}
connected_users = {}


# Оновлена модель з кольором та одержувачем
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(20), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    recipient = db.Column(db.String(50), nullable=True)  # Якщо None - повідомлення бачать усі


with app.app_context():
    db.create_all()


@app.route('/')
def index():
    return render_template('index.html')


# Завантаження історії (тепер фільтруємо, щоб не віддавати чужі привати)
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


# --- ЛОГІКА СОКЕТІВ ---

@socketio.on('register')
def handle_register(data):
    """Юзер зайшов у чат. Записуємо його ID і розсилаємо список онлайн."""
    username = data['username']
    connected_users[username] = request.sid  # request.sid - це унікальний ID поточного підключення
    emit('update_users', list(connected_users.keys()), broadcast=True)


@socketio.on('send_message')
def handle_message(data):
    """Обробка нового повідомлення."""
    recipient = data.get('recipient')

    # 1. Зберігаємо в базу
    new_msg = Message(
        username=data['username'],
        color=data['color'],
        text=data['text'],
        recipient=recipient
    )
    db.session.add(new_msg)
    db.session.commit()

    # 2. Маршрутизація
    if recipient:
        # ПРИВАТНЕ ПОВІДОМЛЕННЯ
        target_sid = connected_users.get(recipient)
        if target_sid:
            # Відправляємо одержувачу
            emit('receive_message', data, to=target_sid)
        # Повертаємо відправнику, щоб він побачив своє повідомлення
        emit('receive_message', data, to=request.sid)
    else:
        # ГЛОБАЛЬНЕ ПОВІДОМЛЕННЯ
        emit('receive_message', data, broadcast=True)


@socketio.on('disconnect')
def handle_disconnect():
    """Юзер закрив вкладку."""
    for user, sid in list(connected_users.items()):
        if sid == request.sid:
            del connected_users[user]
            emit('update_users', list(connected_users.keys()), broadcast=True)
            break


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)