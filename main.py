import telebot
from telebot import types
import sqlite3
import time
import threading
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

TOKEN = '7992178342:AAESfGo9dbybKJjjQ1iybphBLtHJyrSe0Uo'
ADMIN_CHAT_ID = '7805766421'
GROUP_ID = '-1002599159398'
FINISH_GROUP_ID = '-1002591086307'
scheduler = BackgroundScheduler()
scheduler.start()

bot = telebot.TeleBot(TOKEN)

lot_end_time = None


# Создание базы данных и таблиц
def init_db():
    conn = sqlite3.connect('auction.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT UNIQUE,
            phone TEXT,
            is_verified BOOLEAN DEFAULT FALSE
        )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS lots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        town TEXT NOT NULL,
        starting_price REAL NOT NULL,
        bid_step REAL NOT NULL,
        current_bid REAL NOT NULL,
        start_time DATETIME NOT NULL,
        duration DATETIME NOT NULL,
        finished_notified BOOLEAN DEFAULT 0,
        five_min_notified BOOLEAN DEFAULT 0,
        photo_link TEXT,
        video_link TEXT,
        autotheque_link TEXT,
        user_id INTEGER,
        FOREIGN KEY (user_id) REFERENCES users (id)    
    )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bids (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lot_id INTEGER,
            user_id INTEGER,
            amount REAL,
            FOREIGN KEY (lot_id) REFERENCES lots(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.commit()
    conn.close()


init_db()


@bot.message_handler(commands=['start'])
def start_registration(message):
    user_id = message.from_user.id
    # Проверка, существует ли пользователь в БД
    conn = sqlite3.connect('auction.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    existing_user = cursor.fetchone()
    conn.close()

    if existing_user:
        bot.send_message(message.chat.id, "Вы уже зарегистрированы.")
    else:
        bot.send_message(message.chat.id, "Добро пожаловать! Пожалуйста, введите ваше ФИО:")
        bot.register_next_step_handler(message, process_full_name)


def process_full_name(message):
    user_id = message.from_user.id
    full_name = message.text

    # Сохранение данных о пользователе в БД
    conn = sqlite3.connect('auction.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO users (id, full_name) VALUES (?, ?)', (user_id, full_name))
    conn.commit()
    conn.close()

    bot.send_message(message.chat.id, "Спасибо! Теперь введите ваш номер телефона:")
    bot.register_next_step_handler(message, process_phone_number)


def process_phone_number(message):
    user_id = message.from_user.id
    phone = message.text

    # Обновление номера телефона в БД
    conn = sqlite3.connect('auction.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET phone = ? WHERE id = ?', (phone, user_id))
    conn.commit()
    conn.close()

    # Отправка данных администратору
    admin_message = f"Новый пользователь:\nТелефон: {phone}\nID: {user_id}"
    bot.send_message(ADMIN_CHAT_ID, admin_message)

    # Запрос подтверждения
    markup = types.InlineKeyboardMarkup()
    confirm_button = types.InlineKeyboardButton("Подтвердить ✅", callback_data=f"confirm_{user_id}")
    decline_button = types.InlineKeyboardButton("Отклонить ❌", callback_data=f"decline_{user_id}")
    markup.add(confirm_button, decline_button)

    bot.send_message(ADMIN_CHAT_ID, "Подтвердите или отклоните регистрацию:", reply_markup=markup)

    bot.send_message(message.chat.id, "Спасибо за регистрацию! Ваши данные отправлены администратору на проверку.")


@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_') or call.data.startswith('decline_'))
def handle_confirmation(call):
    user_id = int(call.data.split('_')[1])

    conn = sqlite3.connect('auction.db')
    cursor = conn.cursor()

    if call.data.startswith('confirm_'):
        cursor.execute('UPDATE users SET is_verified = 1 WHERE id = ?', (user_id,))
        conn.commit()
        bot.send_message(user_id, "Ваш аккаунт подтвержден! Теперь вы можете делать ставки.")
        bot.send_message(call.message.chat.id, f"Пользователь {user_id} подтвержден.")
    else:
        bot.send_message(user_id, "Ваш аккаунт отклонен. Обратитесь к администратору для уточнения причин.")
        bot.send_message(call.message.chat.id, f"Пользователь {user_id} отклонен.")

    conn.close()


@bot.message_handler(commands=['create'])
def create_lot(message):
    bot.send_message(message.chat.id, "Введите название лота:")
    bot.register_next_step_handler(message, process_description)


def process_description(message):
    title = message.text
    bot.send_message(message.chat.id, "Введите описание лота:")
    bot.register_next_step_handler(message, process_town, title)


def process_town(message, title):
    description = message.text
    bot.send_message(message.chat.id, "Введите город:")
    bot.register_next_step_handler(message, process_starting_price, title, description)


def process_starting_price(message, title, description):
    town = message.text
    bot.send_message(message.chat.id, "Введите начальную стоимость:")
    bot.register_next_step_handler(message, process_bid_step, title, description, town)


def process_bid_step(message, title, description, town):
    try:
        starting_price = float(message.text)
        bot.send_message(message.chat.id, "Введите шаг ставки:")
        bot.register_next_step_handler(message, process_auction_end, title, description, town, starting_price)
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите корректное число для начальной стоимости.")
        bot.register_next_step_handler(message, process_auction_end, title, description)


def process_auction_end(message, title, description, town, starting_price):
    try:
        bid_step = message.text
        bot.send_message(message.chat.id, "Введите срок окончания аукциона (в минутах):")
        bot.register_next_step_handler(message, process_photo_link, title, description, town, starting_price, bid_step)
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите корректное число для шага ставки.")
        bot.register_next_step_handler(message, process_photo_link, title, description, starting_price)


def process_photo_link(message, title, description, town, starting_price, bid_step):
    try:
        end_time = int(message.text)
        bot.send_message(message.chat.id, "Введите ссылку на фото:")
        bot.register_next_step_handler(message, process_video_link, title, description, town, starting_price, bid_step,
                                       end_time)
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите корректное число для срока окончания аукциона.")
        bot.register_next_step_handler(message, process_video_link, title, description, starting_price, bid_step)


def process_video_link(message, title, description, town, starting_price, bid_step, end_time):
    photo_link = message.text
    bot.send_message(message.chat.id, "Введите ссылку на видео:")
    bot.register_next_step_handler(message, process_autotheque_link, title, description, town, starting_price, bid_step,
                                   end_time, photo_link)


def process_autotheque_link(message, title, description, town, starting_price, bid_step, end_time, photo_link):
    video_link = message.text
    bot.send_message(message.chat.id, "Введите ссылку на автотеку:")
    bot.register_next_step_handler(message, process_create_lot, title, description, town, starting_price, bid_step,
                                   end_time, photo_link, video_link)


def get_user_info(user_id):
    conn = sqlite3.connect('auction.db')
    cursor = conn.cursor()
    cursor.execute('SELECT full_name, phone FROM users WHERE id = ?', (user_id,))
    result = cursor.fetchone()

    if result:
        full_name, phone = result  # Распаковываем результат
        return full_name, phone
    else:
        return None, None


def process_create_lot(message, title, description, town, starting_price, bid_step, end_time, photo_link,
                       video_link):
    autotheque_link = message.text
    user_id = message.from_user.id

    conn = sqlite3.connect('auction.db')
    cursor = conn.cursor()

    # Сохранение лота в базу данных
    cursor.execute('''
    INSERT INTO lots (title, description, starting_price, bid_step, current_bid, start_time, duration,
                       photo_link, video_link, autotheque_link, user_id, town)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (title, description, starting_price, bid_step, starting_price,
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    end_time,
                    photo_link,
                    video_link,
                    autotheque_link, user_id, town))

    conn.commit()
    conn.close()

    full_name = get_user_info(user_id)[0]
    phone = get_user_info(user_id)[1]

    # Публикация лота в группе (примерный текст сообщения)
    lot_message = f"""📦 * Новый лот: *{title}*
📝 * Описание: {description}
💰 * Начальная стоимость: {starting_price}₽
🔼 * Шаг ставки: {bid_step}₽
🏠 * Город: {town}

👨 * Владелец: *{full_name} | {phone}*"""

    markup = types.InlineKeyboardMarkup()

    # Добавляем кнопки для фото и видео
    if photo_link:
        button_photo = types.InlineKeyboardButton(text="📸 Фото", url=photo_link)
        button_autotheque = types.InlineKeyboardButton(text="📈 Автотека", url=autotheque_link)
        markup.add(button_photo, button_autotheque)

    if video_link:
        button_video = types.InlineKeyboardButton(text="🎥 Видео", url=video_link)
        markup.add(button_video)

    # Здесь можно отправить сообщение в группу (замените chat_id на нужный)
    bot.send_photo(chat_id=GROUP_ID, photo=photo_link, caption=lot_message, reply_markup=markup)
    bot.send_message(message.chat.id, 'Вы создали лот. Поздравляем! ✅')


# Функция для получения всех доступных лотов
def get_all_lots():
    conn = sqlite3.connect('auction.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, title FROM lots')
    lots = cursor.fetchall()
    conn.close()
    return lots


def is_user_verified(message):
    user_id = message.from_user.id
    conn = sqlite3.connect('auction.db')
    cursor = conn.cursor()
    cursor.execute('SELECT is_verified FROM users WHERE id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0]


@bot.message_handler(commands=['lots'])
def handle_lots(message):
    if not is_user_verified(message):
        bot.reply_to(message, "Вы не подтвержденный пользователь! Зарегистрируйтесь с помощью /start")
        return

    lots = get_all_lots()

    if not lots:
        bot.reply_to(message, "Нет доступных лотов.")
        return

    markup = types.InlineKeyboardMarkup()

    for lot in lots:
        lot_id, title = lot
        button = types.InlineKeyboardButton(text=title, callback_data=f'lot_{lot_id}')
        markup.add(button)

    bot.send_message(message.chat.id, "Доступные лоты:", reply_markup=markup)


def get_time_left(start_time_str, end_time_minutes):
    start_time = datetime.fromisoformat(start_time_str)
    end_time = start_time + timedelta(minutes=end_time_minutes)
    remaining = end_time - datetime.now()

    if remaining.total_seconds() <= 0:
        return "Аукцион завершен", 0

    days, seconds = remaining.days, remaining.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{days}д {hours}ч {minutes}м", remaining.total_seconds()


@bot.callback_query_handler(func=lambda call: call.data.startswith('lot_'))
def handle_lot_selection(call):
    lot_id = int(call.data.split('_')[1])

    conn = sqlite3.connect('auction.db')
    cursor = conn.cursor()
    cursor.execute(
        '''SELECT lots.title, lots.description, lots.current_bid, 
              lots.bid_step, lots.start_time, lots.duration,
              lots.five_min_notified, lots.finished_notified,
              lots.photo_link, lots.video_link, lots.autotheque_link, 
              users.full_name, users.phone 
       FROM lots 
       JOIN users ON lots.user_id = users.id 
       WHERE lots.id = ?''',
        (lot_id,))
    lot_info = cursor.fetchone()

    if lot_info:
        (title, description, current_bid, bid_step, start_time, end_time,
         five_min_notified, finished_notified, photo_link, video_link,
         autotheque_link, full_name, phone) = lot_info

        time_left_str, remaining_seconds = get_time_left(start_time, end_time)

        # Если аукцион завершен

        response_message = f"Лот: *{title}*\nОписание: {description}\nТекущая ставка: *{current_bid}₽*\nШаг ставки: {bid_step}₽\nВремя: {time_left_str}\nВладелец: {full_name} | {phone}"

        markup = types.InlineKeyboardMarkup()
        time_left_button = types.InlineKeyboardButton(
            text=f"🕒 Осталось: {time_left_str}",
            callback_data='time_refresh')
        markup.add(time_left_button)

        # Кнопки для ставок и медиа
        # ... (ваш существующий код)

        msg = bot.send_photo(chat_id=call.message.chat.id, photo=photo_link,
                             caption=response_message, reply_markup=markup)

        # Запуск обновления таймера
        if remaining_seconds > 0:
            scheduler.add_job(
                update_timer,
                'interval',
                minutes=1,
                args=[msg.chat.id, msg.message_id, lot_id],
                id=f'timer_{lot_id}_{msg.message_id}'
            )

            # Планируем уведомление за 5 минут
            if not five_min_notified and remaining_seconds > 300:
                notification_time = datetime.now() + timedelta(seconds=remaining_seconds - 300)
                scheduler.add_job(
                    send_5min_notification,
                    'date',
                    run_date=notification_time,
                    args=[lot_id, title],
                    id=f'5min_{lot_id}'
                )


    conn.close()
    bot.answer_callback_query(call.id)


def update_timer(chat_id, msg_id, lot_id):
    conn = sqlite3.connect('auction.db')
    cursor = conn.cursor()
    cursor.execute(
        '''SELECT start_time, duration, five_min_notified 
           FROM lots WHERE id = ?''',
        (lot_id,))
    start_time, duration, five_min_notified = cursor.fetchone()

    time_left_str, remaining_seconds = get_time_left(start_time, duration)

    # Проверка на 5 минут
    if remaining_seconds <= 300 and not five_min_notified:
        bot.send_message(chat_id, f"⚠️ Аукцион завершается через 5 минут! Успейте сделать ставку!")
        cursor.execute('UPDATE lots SET five_min_notified = 1 WHERE id = ?', (lot_id,))
        conn.commit()

    # Обновление интерфейса
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        text=f"🕒 Осталось: {time_left_str}",
        callback_data='time_refresh'
    ))

    try:
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=markup)
    except Exception as e:
        print(f"Ошибка обновления: {e}")
        scheduler.remove_job(f'timer_{lot_id}_{msg_id}')

    # Удаление задания при завершении
    if "завершен" in time_left_str:
        scheduler.remove_job(f'timer_{lot_id}_{msg_id}')

    conn.close()


def send_5min_notification(lot_id, title):
    bot.send_message(
        GROUP_ID,
        f"⚠️ Внимание! Аукцион на лот *{title}* (ID: {lot_id}) "
        f"завершится через 5 минут! Успейте сделать ставку!",
    )


def send_finish_notification(lot_id, title):
    bot.send_message(
        GROUP_ID,
        f"Аукцион с лотом ID {lot_id} завершился!",
    )
    bot.send_message(FINISH_GROUP_ID,
                     f"Аукцион завершен!\nЛот: {title}\nID: {lot_id}")



@bot.callback_query_handler(func=lambda call: call.data.startswith('place_bid_'))
def handle_place_bid(call):
    user_id = call.from_user.id
    # Проверка, существует ли пользователь в БД
    conn = sqlite3.connect('auction.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    existing_user = cursor.fetchone()
    conn.close()

    if existing_user:
        data = call.data.split('_')
        lot_id = int(data[2])
        min_bid = float(data[3])

        # Запрашиваем сумму ставки у пользователя
        bot.send_message(call.message.chat.id, f"Введите сумму ставки (минимум {min_bid}):")
        bot.register_next_step_handler(call.message, process_bid_amount, lot_id, min_bid)
    else:
        bot.send_message(call.message.chat.id,
                         "Не зарегистрированные пользователи не могут сделать ставку\nПожалуйста, используйте команду /start для регистрации.")


def process_bid_amount(message, lot_id, min_bid):
    try:
        bid_amount = float(message.text)

        if bid_amount < min_bid:
            bot.send_message(message.chat.id,
                             f"Ставка должна быть больше или равна минимальной ({min_bid}). Попробуйте снова.")
            bot.register_next_step_handler(message, process_bid_amount, lot_id, min_bid)
            return

        # Обновление текущей ставки в базе данных
        conn = sqlite3.connect('auction.db')
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT lots.current_bid, lots.title, lots.photo_link, 
                  users.full_name, users.phone  
           FROM lots 
           JOIN users ON lots.user_id = users.id 
           WHERE lots.id = ?''',
            (lot_id,))
        current_bid = cursor.fetchone()
        title = current_bid[1]
        full_name = current_bid[3]
        phone = current_bid[4]
        photo = current_bid[2]

        if current_bid is None:
            bot.send_message(message.chat.id, "Лот не найден.")
            return

        current_bid = current_bid[0]

        if bid_amount > current_bid:
            cursor.execute("UPDATE lots SET current_bid=? WHERE id=?", (bid_amount, lot_id))
            conn.commit()
            bot.send_message(message.chat.id, f"Ставка {bid_amount} успешно добавлена на лот ID {lot_id}.")
            bot.send_photo(chat_id=GROUP_ID, photo=photo,
                           caption=f"""Лот: {title}\nВладелец: {full_name} | {phone}\nСтавка {bid_amount} перебивает {current_bid} успешно на лот ID {lot_id}""")

        else:
            bot.send_message(message.chat.id, f"Ставка должна быть больше текущей ({current_bid}). Попробуйте снова.")
            bot.register_next_step_handler(message, process_bid_amount, lot_id, min_bid)

    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите корректную сумму ставки.")
        bot.register_next_step_handler(message, process_bid_amount, lot_id, min_bid)


# Обработчик текстовых сообщений (если нужно)
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    user_id = message.from_user.id
    conn = sqlite3.connect('auction.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    existing_user = cursor.fetchone()
    conn.close()

    if existing_user:
        bot.reply_to(message, "Пожалуйста, перепроверьте ввод команды")
    else:
        bot.reply_to(message, "Пожалуйста, используйте команду /start для регистрации.")


if __name__ == '__main__':
    bot.polling(none_stop=True)
