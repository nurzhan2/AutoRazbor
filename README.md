# АвтоЗапчасти — Инструкция по запуску

## Структура проекта

```
autoparts/
├── main.py                  # Точка входа FastAPI + планировщик + бот
├── requirements.txt
├── .env.example             # Шаблон переменных окружения
├── app/
│   ├── models/
│   │   ├── models.py        # SQLAlchemy модели (User, Product, Video, Payment, SyncLog)
│   │   └── database.py      # Подключение к БД
│   ├── routers/
│   │   ├── auth.py          # /login, /logout
│   │   ├── dashboard.py     # /dashboard, /videos
│   │   ├── catalog.py       # /catalog, /catalog/{id}
│   │   └── admin.py         # /admin/*
│   ├── services/
│   │   ├── auth.py          # JWT, bcrypt, генерация логина/пароля
│   │   ├── catalog.py       # Парсинг Avito XML/CSV, обновление каталога
│   │   └── notifications.py # Уведомления об истечении подписки
│   ├── templates/           # Jinja2 HTML шаблоны
│   └── static/              # CSS, JS, img
└── bot/
    └── bot.py               # Telegram-бот (aiogram 3)
```

## 1. Установка зависимостей

```bash
cd autoparts
pip install -r requirements.txt
```

## 2. Настройка окружения

```bash
cp .env.example .env
nano .env
```

Заполните обязательные поля:
- `BOT_TOKEN` — токен от @BotFather
- `ADMIN_TELEGRAM_ID` — ваш Telegram ID (получить у @userinfobot)
- `SECRET_KEY` — любая случайная строка 32+ символов
- `SITE_URL` — адрес вашего сайта (https://yourdomain.ru)
- `AVITO_FEED_URL` — ссылка на XML/CSV выгрузку Avito

## 3. Запуск для разработки

```bash
cd autoparts
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Откройте: http://localhost:8000

## 4. Запуск на сервере (systemd)

Создайте файл `/etc/systemd/system/autoparts.service`:

```ini
[Unit]
Description=AutoParts Site + Bot
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/autoparts
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
EnvironmentFile=/var/www/autoparts/.env

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable autoparts
systemctl start autoparts
```

## 5. Nginx (обратный прокси)

```nginx
server {
    listen 80;
    server_name yourdomain.ru;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    location /static/ {
        alias /var/www/autoparts/app/static/;
    }
}
```

Затем HTTPS через Certbot:
```bash
certbot --nginx -d yourdomain.ru
```

## 6. Первый вход в админку

URL: https://yourdomain.ru/admin  
Логин/пароль из .env (по умолчанию: admin / admin123)

**Обязательно смените пароль в .env перед деплоем!**

## 7. Добавление видео

Зайдите в /admin/videos и добавьте 3 видео. Поддерживаются:
- YouTube: https://youtube.com/watch?v=ID или https://youtu.be/ID
- Vimeo: https://vimeo.com/ID
- Прямая ссылка на .mp4

## 8. Настройка Avito выгрузки

1. В личном кабинете Avito: Настройки → Автозагрузка → Скопируйте ссылку на файл
2. Вставьте в .env как `AVITO_FEED_URL`
3. В /admin/catalog нажмите «Обновить сейчас» для тестирования

Поддерживаемые форматы: XML (Avito), YML (Яндекс.Маркет), CSV

## 9. Подключение платёжной системы

В `bot/bot.py` замените функцию `cb_pay` и `cb_pay_stub` на интеграцию с:
- **YooKassa**: используйте `yookassa` SDK, создайте Payment и верните ссылку
- **Robokassa**: сгенерируйте URL оплаты, обработайте Result URL webhook
- **Telegram Payments**: добавьте `send_invoice()` через aiogram

После получения успешного webhook вызовите:
```python
await process_successful_payment(message, telegram_id)
```

## 10. Проверка работы

- Сайт: https://yourdomain.ru/login
- Админка: https://yourdomain.ru/admin
- Бот: t.me/your_bot_name
- Тест оплаты: нажать «Тестовая оплата (заглушка)» в боте
