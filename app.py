"""
Rezzex Chat Server v2.0
Профессиональный сервер для кастомного чата Roblox
Поддерживает: глобальный чат, кэширование, статистику, CORS, защиту от спама
Владелец: HollyFolly04444
"""

from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from datetime import datetime, timedelta
import json
import os
import re
from collections import deque
from typing import List, Dict, Any, Optional
import time
from dataclasses import dataclass, asdict
import logging

# ===== НАСТРОЙКИ =====
MAX_MESSAGES = 200  # Максимум сообщений в истории
MAX_MESSAGE_LENGTH = 500  # Макс длина одного сообщения
RATE_LIMIT_SECONDS = 1  # Минимальный интервал между сообщениями от одного пользователя
CLEANUP_INTERVAL = 60  # Очистка старых сообщений каждые 60 секунд

# ===== ЛОГГИРОВАНИЕ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('RezzexChat')

# ===== ИНИЦИАЛИЗАЦИЯ FLASK =====
app = Flask(__name__)
CORS(app)  # Разрешаем запросы с любых источников (важно для Roblox)

# ===== ХРАНЕНИЕ ДАННЫХ =====
@dataclass
class Message:
    """Модель сообщения"""
    user: str
    text: str
    time: str
    timestamp: float
    id: str  # Уникальный ID для дедупликации

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь для JSON"""
        return {
            'user': self.user,
            'text': self.text,
            'time': self.time,
            'id': self.id
        }

class ChatStorage:
    """Класс для управления хранилищем сообщений"""
    
    def __init__(self, max_size: int = MAX_MESSAGES):
        self.messages: deque = deque(maxlen=max_size)
        self.user_last_message: Dict[str, float] = {}  # Для защиты от спама
        self._cleanup_timer = time.time()
    
    def add_message(self, user: str, text: str, time_str: str) -> Optional[Message]:
        """Добавляет сообщение с защитой от спама"""
        current_time = time.time()
        
        # Проверка на спам
        if user in self.user_last_message:
            if current_time - self.user_last_message[user] < RATE_LIMIT_SECONDS:
                logger.warning(f"Спам-защита: {user} пытается отправить слишком много сообщений")
                return None
        
        # Проверка длины
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[:MAX_MESSAGE_LENGTH] + "..."
        
        # Создаём уникальный ID
        msg_id = f"{user}_{int(current_time * 1000)}"
        
        # Создаём сообщение
        message = Message(
            user=user[:50],  # Ограничиваем длину имени
            text=text,
            time=time_str,
            timestamp=current_time,
            id=msg_id
        )
        
        self.messages.append(message)
        self.user_last_message[user] = current_time
        
        # Периодическая очистка
        if current_time - self._cleanup_timer > CLEANUP_INTERVAL:
            self._cleanup_old_messages()
            self._cleanup_timer = current_time
        
        logger.info(f"Новое сообщение от {user}: {text[:30]}...")
        return message
    
    def get_messages(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Возвращает последние N сообщений"""
        result = []
        for msg in list(self.messages)[-limit:]:
            result.append(msg.to_dict())
        return result
    
    def _cleanup_old_messages(self):
        """Очищает сообщения старше 24 часов"""
        cutoff = time.time() - (24 * 3600)
        old_count = 0
        while self.messages and self.messages[0].timestamp < cutoff:
            self.messages.popleft()
            old_count += 1
        if old_count > 0:
            logger.info(f"Очищено {old_count} старых сообщений")

# ===== ГЛОБАЛЬНЫЙ ИНСТАНС =====
storage = ChatStorage()

# ===== СТАТИСТИКА СЕРВЕРА =====
class ServerStats:
    def __init__(self):
        self.start_time = time.time()
        self.total_messages = 0
        self.total_users = set()
        self.requests_count = 0
    
    def record_message(self, user: str):
        self.total_messages += 1
        self.total_users.add(user)
    
    def record_request(self):
        self.requests_count += 1
    
    def get_stats(self) -> Dict[str, Any]:
        uptime = int(time.time() - self.start_time)
        return {
            'uptime_seconds': uptime,
            'uptime_formatted': self._format_uptime(uptime),
            'total_messages': self.total_messages,
            'total_users': len(self.total_users),
            'requests_count': self.requests_count,
            'messages_in_memory': len(storage.messages),
            'max_messages': MAX_MESSAGES
        }
    
    @staticmethod
    def _format_uptime(seconds: int) -> str:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{days}д {hours}ч {minutes}м {secs}с"

stats = ServerStats()

# ===== РОУТЫ API =====

@app.route('/', methods=['GET'])
def index():
    """Корневой роут с информацией о сервере"""
    return jsonify({
        'name': 'Rezzex Chat Server',
        'version': '2.0',
        'author': 'HollyFolly04444',
        'description': 'Профессиональный сервер для кастомного чата Roblox',
        'endpoints': {
            '/': 'GET - Информация о сервере',
            '/send': 'POST - Отправить сообщение',
            '/get': 'GET - Получить последние сообщения',
            '/stats': 'GET - Статистика сервера',
            '/ping': 'GET - Проверка соединения',
            '/clear': 'POST - Очистить историю (требуется ключ)'
        },
        'status': 'online',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/ping', methods=['GET'])
def ping():
    """Проверка соединения"""
    return jsonify({
        'status': 'pong',
        'timestamp': datetime.now().isoformat(),
        'server_time': time.time()
    })

@app.route('/send', methods=['POST'])
def send_message():
    """Отправка сообщения"""
    stats.record_request()
    
    try:
        # Получаем данные
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Неверный формат данных'}), 400
        
        user = data.get('user', 'Unknown')
        text = data.get('text', '')
        time_str = data.get('time', datetime.now().strftime('%H:%M'))
        
        # Базовая валидация
        if not text or text.strip() == '':
            return jsonify({'error': 'Сообщение не может быть пустым'}), 400
        
        # Добавляем сообщение
        message = storage.add_message(user, text.strip(), time_str)
        if not message:
            return jsonify({'error': 'Превышен лимит сообщений (спам-защита)'}), 429
        
        stats.record_message(user)
        
        return jsonify({
            'status': 'success',
            'message': message.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"Ошибка в /send: {str(e)}")
        return jsonify({'error': f'Внутренняя ошибка сервера: {str(e)}'}), 500

@app.route('/get', methods=['GET'])
def get_messages():
    """Получение сообщений"""
    stats.record_request()
    
    try:
        limit = request.args.get('limit', 50, type=int)
        limit = min(max(limit, 1), 100)  # Ограничиваем от 1 до 100
        
        messages = storage.get_messages(limit)
        
        return jsonify(messages), 200
        
    except Exception as e:
        logger.error(f"Ошибка в /get: {str(e)}")
        return jsonify({'error': f'Внутренняя ошибка сервера: {str(e)}'}), 500

@app.route('/stats', methods=['GET'])
def get_stats():
    """Статистика сервера"""
    stats.record_request()
    
    return jsonify({
        **stats.get_stats(),
        'settings': {
            'max_messages': MAX_MESSAGES,
            'max_message_length': MAX_MESSAGE_LENGTH,
            'rate_limit_seconds': RATE_LIMIT_SECONDS,
            'cleanup_interval_seconds': CLEANUP_INTERVAL
        },
        'timestamp': datetime.now().isoformat()
    })

@app.route('/clear', methods=['POST'])
def clear_messages():
    """Очистка истории (только с ключом)"""
    stats.record_request()
    
    try:
        data = request.get_json()
        admin_key = data.get('key', '') if data else ''
        
        # Защита: нужно знать секретный ключ
        SECRET_KEY = os.environ.get('ADMIN_KEY', 'default_secure_key_123')
        
        if admin_key != SECRET_KEY:
            return jsonify({'error': 'Неверный ключ доступа'}), 403
        
        # Очищаем хранилище
        storage.messages.clear()
        storage.user_last_message.clear()
        
        logger.warning("История сообщений была очищена администратором")
        
        return jsonify({
            'status': 'success',
            'message': 'История очищена'
        }), 200
        
    except Exception as e:
        logger.error(f"Ошибка в /clear: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/users', methods=['GET'])
def get_users():
    """Получить список активных пользователей"""
    stats.record_request()
    
    try:
        # Пользователи, которые писали за последние 5 минут
        cutoff = time.time() - 300
        active_users = set()
        
        for msg in storage.messages:
            if msg.timestamp > cutoff and msg.user not in active_users:
                active_users.add(msg.user)
        
        return jsonify({
            'active_users': list(active_users),
            'total_active': len(active_users),
            'all_time_users': len(storage.user_last_message)
        }), 200
        
    except Exception as e:
        logger.error(f"Ошибка в /users: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ===== ОБРАБОТКА ОШИБОК =====

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint не найден'}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({'error': 'Метод не разрешён'}), 405

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Внутренняя ошибка: {str(error)}")
    return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

# ===== ЗАПУСК СЕРВЕРА =====

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    logger.info(f"🚀 Запуск Rezzex Chat Server v2.0")
    logger.info(f"📡 Порт: {port}")
    logger.info(f"🐞 Режим отладки: {debug}")
    logger.info(f"📊 Максимум сообщений: {MAX_MESSAGES}")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )
