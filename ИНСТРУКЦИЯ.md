# Gemini Suite — Полное руководство по управлению

## Оглавление

1. [Обзор системы](#обзор-системы)
2. [Установка](#установка)
3. [Настройка](#настройка)
4. [Управление CLI-консолью](#управление-cli-консолью)
5. [Управление прокси-сервером](#управление-прокси-сервером)
6. [Удалённое управление консолями](#удалённое-управление-консолями)
7. [AI-управление через Gemini Flash](#ai-управление-через-gemini-flash)
8. [REST API — полный справочник](#rest-api--полный-справочник)
9. [Dashboard — веб-панель](#dashboard--веб-панель)
10. [Примеры использования](#примеры-использования)
11. [Устранение неполадок](#устранение-неполадок)

---

## Обзор системы

**Gemini Suite** состоит из двух компонентов:

```
┌─────────────────────┐          ┌──────────────────────────┐
│   gemini-cli (ПК)   │◄── WS ──►│   gemini-proxy (сервер)  │
│                     │          │                          │
│  Интерактивный REPL │          │  FastAPI прокси          │
│  Подсветка кода     │          │  Anthropic API совмест.  │
│  Файловые операции  │          │  AI-управление (Flash)   │
│  Shell-команды      │          │  WebSocket менеджер      │
│  Удалённый режим    │          │  Веб-Dashboard           │
└─────────────────────┘          └──────────────────────────┘
       │                                    ▲
       │                                    │
       └──── Google Gemini API ─────────────┘
```

Ключевая фишка: **прокси-сервер может управлять подключёнными CLI-консолями через AI** — вы отправляете команду на естественном языке, Gemini 2.5 Flash интерпретирует её и выполняет нужное действие на удалённых машинах.

---

## Установка

### Сервер (gemini-proxy)

```bash
# 1. Клонируем / копируем файлы
cd gemini-suite/gemini-proxy

# 2. Запускаем установщик (создаст systemd сервис)
sudo bash install.sh

# 3. Настраиваем ключи
sudo nano /etc/gemini-proxy/config.env
```

Содержимое `/etc/gemini-proxy/config.env`:
```bash
GEMINI_API_KEY=ваш_ключ_google_gemini
PROXY_API_KEY=секретный_ключ_для_доступа_к_прокси
PORT=8000
HOST=0.0.0.0
MANAGEMENT_MODEL=gemini-2.5-flash-preview-05-20
```

```bash
# 4. Запуск
sudo systemctl start gemini-proxy
sudo systemctl enable gemini-proxy   # автозапуск

# 5. Проверка
curl http://localhost:8000/health
```

### Клиент (gemini-cli)

```bash
# 1. Установка
cd gemini-suite/gemini-cli
bash install.sh

# 2. Запуск и начальная настройка
gemini-cli
# Внутри приложения:
/setup     # ввести API ключ Google Gemini
```

---

## Настройка

### Конфигурация CLI (~/.gemini-cli/config.json)

```json
{
  "api_key": "AIza...",
  "model": "gemini-2.5-flash-preview-05-20",
  "server_url": "ws://ваш-сервер:8000/ws/remote",
  "timeout": 60,
  "max_tokens": 8192,
  "temperature": 0.7,
  "auto_remote": false,
  "client_name": "my-workstation"
}
```

| Параметр | Описание |
|----------|----------|
| `api_key` | Ключ Google Gemini API |
| `model` | Модель по умолчанию |
| `server_url` | WebSocket URL прокси-сервера |
| `timeout` | Таймаут запросов (секунды) |
| `max_tokens` | Максимум токенов в ответе |
| `temperature` | Температура генерации (0.0-1.0) |
| `auto_remote` | Автоподключение к серверу при старте |
| `client_name` | Имя клиента (используется как часть ID) |

### Конфигурация прокси (переменные окружения)

| Переменная | Описание | По умолчанию |
|------------|----------|-------------|
| `GEMINI_API_KEY` | Ключ Google Gemini | (обязательно) |
| `PROXY_API_KEY` | Ключ доступа к прокси | `secret-proxy-key` |
| `PORT` | Порт сервера | `8000` |
| `HOST` | Хост | `0.0.0.0` |
| `MANAGEMENT_MODEL` | Модель для AI-управления | `gemini-2.5-flash-preview-05-20` |

---

## Управление CLI-консолью

### Команды REPL

| Команда | Действие |
|---------|----------|
| `/help` | Показать справку |
| `/clear` | Очистить историю разговора |
| `/exit` | Выход |
| `/setup` | Ввести API ключ |
| `/config` | Показать настройки |
| `/model <имя>` | Переключить модель |
| `/models` | Список доступных моделей |
| `/remote on` | Подключиться к прокси для удалённого управления |
| `/remote off` | Отключить удалённый режим |
| `/file read <путь>` | Прочитать файл с подсветкой |
| `/file write <путь>` | Записать последний блок кода в файл |
| `/exec <команда>` | Выполнить shell-команду (с подтверждением) |

### Примеры работы

```
▶ Напиши скрипт бэкапа для PostgreSQL

  [Gemini генерирует код с подсветкой синтаксиса]

▶ /file write ~/backup.sh
  ✓ Записано: /home/user/backup.sh (1247 байт)

▶ /exec chmod +x ~/backup.sh
  ┌─ Команда ─┐
  │ chmod +x ~/backup.sh │
  └──────────┘
  Выполнить? [y/n]: y
  Exit code: 0

▶ /model gemini-2.5-pro-preview-05-06
  ✓ Модель: gemini-2.5-pro-preview-05-06
```

---

## Управление прокси-сервером

### Systemd

```bash
# Статус
sudo systemctl status gemini-proxy

# Запуск / остановка / перезапуск
sudo systemctl start gemini-proxy
sudo systemctl stop gemini-proxy
sudo systemctl restart gemini-proxy

# Логи
sudo journalctl -u gemini-proxy -f

# Автозапуск
sudo systemctl enable gemini-proxy
```

### Проверка здоровья

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"2.0.0","gemini_configured":true,"management_model":"gemini-2.5-flash-preview-05-20","connected_clients":2}
```

---

## Удалённое управление консолями

### Схема работы

```
  Вы (curl/браузер/скрипт)
         │
         ▼
   POST /v1/remote/send ──► gemini-proxy ──► [WebSocket] ──► gemini-cli (ПК-1)
                                                            gemini-cli (ПК-2)
                                                            gemini-cli (ПК-3)
```

### Шаг 1: Подключаем CLI к серверу

На каждой машине, где запущен gemini-cli:

```
▶ /remote on
  Подключение к ws://your-server:8000/ws/remote...
  ✓ Удалённый режим включён (id: workstation-153042)
```

### Шаг 2: Смотрим подключённых клиентов

```bash
curl -H "X-API-Key: secret-proxy-key" http://server:8000/v1/remote/clients
```

Ответ:
```json
{
  "clients": [
    {
      "client_id": "workstation-153042",
      "ip": "192.168.1.10",
      "status": "idle",
      "connected_at": "2026-03-20T12:30:42"
    },
    {
      "client_id": "laptop-153115",
      "ip": "192.168.1.15",
      "status": "idle",
      "connected_at": "2026-03-20T12:31:15"
    }
  ],
  "count": 2
}
```

### Шаг 3: Отправляем промпт конкретному клиенту

```bash
curl -X POST http://server:8000/v1/remote/send \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret-proxy-key" \
  -d '{
    "client_id": "workstation-153042",
    "prompt": "Напиши hello world на Python",
    "timeout": 60
  }'
```

Ответ:
```json
{
  "client_id": "workstation-153042",
  "prompt": "Напиши hello world на Python",
  "response": "```python\nprint(\"Hello, World!\")\n```\nЭтот код выводит приветствие..."
}
```

### Шаг 4: Broadcast — команда всем клиентам

```bash
curl -X POST "http://server:8000/v1/remote/broadcast?prompt=Покажи%20версию%20Python" \
  -H "X-API-Key: secret-proxy-key"
```

---

## AI-управление через Gemini Flash

**Это главная фишка** — вместо того чтобы вручную смотреть ID клиентов и формировать JSON,
вы просто пишете команду на естественном языке. Gemini 2.5 Flash интерпретирует команду
и выполняет нужное действие.

### Эндпоинт

```
POST /v1/manage
Content-Type: application/json
X-API-Key: your-proxy-key
```

### Примеры команд

#### Посмотреть клиентов
```bash
curl -X POST http://server:8000/v1/manage \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret-proxy-key" \
  -d '{"command": "покажи подключённых клиентов"}'
```

#### Отправить задачу клиенту
```bash
curl -X POST http://server:8000/v1/manage \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret-proxy-key" \
  -d '{"command": "отправь первому клиенту: напиши скрипт бэкапа MySQL с ротацией за 7 дней"}'
```

#### Статистика
```bash
curl -X POST http://server:8000/v1/manage \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret-proxy-key" \
  -d '{"command": "покажи статистику сервера"}'
```

#### Массовая команда
```bash
curl -X POST http://server:8000/v1/manage \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret-proxy-key" \
  -d '{"command": "попроси все консоли проверить свободное место на диске и доложить"}'
```

#### Указать конкретного клиента
```bash
curl -X POST http://server:8000/v1/manage \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret-proxy-key" \
  -d '{
    "command": "напиши nginx конфиг для reverse proxy",
    "target_client": "workstation-153042"
  }'
```

#### Быстрая команда через GET
```bash
curl "http://server:8000/v1/manage/статистика" \
  -H "X-API-Key: secret-proxy-key"
```

### Как это работает внутри

```
1. Вы отправляете: "отправь первому клиенту: напиши скрипт бэкапа"
2. Прокси вызывает Gemini 2.5 Flash с контекстом:
   - список подключённых клиентов
   - статистика сервера
   - ваша команда
3. Flash возвращает JSON с решением:
   {"action": "send_prompt", "client_id": "...", "prompt": "..."}
4. Прокси исполняет решение: отправляет промпт клиенту через WebSocket
5. Клиент обрабатывает промпт через Gemini и возвращает ответ
6. Вы получаете результат
```

---

## REST API — полный справочник

Все эндпоинты требуют заголовок `X-API-Key` (кроме `/health` и `/`).

### Основные

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| `POST` | `/v1/messages` | Anthropic-совместимый API (streaming + non-streaming) |
| `POST` | `/v1/gemini/generate` | Нативный Gemini endpoint |
| `GET` | `/health` | Проверка здоровья |
| `GET` | `/` | Информация об API |
| `GET` | `/docs` | Swagger документация |

### Удалённое управление

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| `GET` | `/v1/remote/clients` | Список подключённых CLI |
| `POST` | `/v1/remote/send` | Отправить промпт клиенту |
| `POST` | `/v1/remote/broadcast` | Отправить промпт всем |
| `WS` | `/ws/remote` | WebSocket для CLI-подключений |

### AI-управление

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| `POST` | `/v1/manage` | Команда на естественном языке |
| `GET` | `/v1/manage/{command}` | Быстрая команда через URL |

### Anthropic-совместимый формат

Можно направить любой инструмент, поддерживающий Anthropic API, на прокси:

```bash
# Вместо https://api.anthropic.com
export ANTHROPIC_BASE_URL=http://your-server:8000

# Используйте как обычно — прокси транслирует запросы в Gemini формат
curl -X POST http://server:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret-proxy-key" \
  -d '{
    "model": "claude-3-sonnet",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 1024
  }'
# → прокси переведёт в gemini-1.5-flash и вернёт ответ в формате Anthropic
```

Маппинг моделей:
| Anthropic | → Gemini |
|-----------|----------|
| claude-3-opus | gemini-1.5-pro |
| claude-3-sonnet | gemini-1.5-flash |
| claude-3-haiku | gemini-2.0-flash |
| claude-3.5-sonnet | gemini-2.5-pro |
| claude-3.5-haiku | gemini-2.5-flash |

---

## Dashboard — веб-панель

Откройте в браузере:
```
http://your-server:8000/dashboard
```

На панели отображается:
- **Статистика** — количество запросов, токенов, подключённых клиентов
- **Подключённые клиенты** — ID, IP, статус (idle/busy), время подключения
- **Консоль управления** — текстовое поле для отправки AI-команд прямо из браузера
- **История запросов** — последние 20 запросов с моделями и токенами

Панель автоматически обновляется каждые 10 секунд.

---

## Примеры использования

### Сценарий 1: Генерация кода на удалённой машине

```bash
# С любого компьютера
curl -X POST http://server:8000/v1/manage \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret-proxy-key" \
  -d '{"command": "попроси первую консоль написать FastAPI приложение с CRUD для блога"}'
```

### Сценарий 2: Мониторинг нескольких серверов

```bash
curl -X POST http://server:8000/v1/manage \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret-proxy-key" \
  -d '{"command": "попроси все консоли написать скрипт, который проверит загрузку CPU, RAM и диска"}'
```

### Сценарий 3: Использование как Anthropic прокси

```python
# Python — используем anthropic SDK, но через наш прокси
import anthropic

client = anthropic.Anthropic(
    api_key="secret-proxy-key",
    base_url="http://your-server:8000"
)

message = client.messages.create(
    model="claude-3-sonnet",  # → будет использован gemini-1.5-flash
    max_tokens=1024,
    messages=[{"role": "user", "content": "Привет!"}]
)
print(message.content[0].text)
```

### Сценарий 4: Автоматизация через cron

```bash
# Каждый час просить консоль генерировать отчёт
0 * * * * curl -s -X POST http://server:8000/v1/manage \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret-proxy-key" \
  -d '{"command": "попроси первую консоль написать summary по логам за последний час"}'
```

### Сценарий 5: Скрипт управления на Python

```python
import httpx

PROXY = "http://server:8000"
KEY = "secret-proxy-key"
HEADERS = {"X-API-Key": KEY, "Content-Type": "application/json"}

# Список клиентов
r = httpx.get(f"{PROXY}/v1/remote/clients", headers=HEADERS)
clients = r.json()["clients"]
print(f"Онлайн: {len(clients)} клиентов")

# AI-команда
r = httpx.post(f"{PROXY}/v1/manage", headers=HEADERS, json={
    "command": "попроси всех клиентов показать свою версию Python"
})
print(r.json())

# Прямая отправка
for client in clients:
    r = httpx.post(f"{PROXY}/v1/remote/send", headers=HEADERS, json={
        "client_id": client["client_id"],
        "prompt": "Напиши однострочник: проверка свободного места на /",
        "timeout": 30,
    })
    print(f"{client['client_id']}: {r.json()['response'][:100]}")
```

---

## Устранение неполадок

### CLI не подключается к серверу

```bash
# Проверить, что сервер доступен
curl http://server:8000/health

# Проверить WebSocket
wscat -c ws://server:8000/ws/remote

# Убедиться, что в config.json правильный server_url
cat ~/.gemini-cli/config.json
```

### Gemini API возвращает ошибку

```bash
# Проверить ключ
curl "https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_KEY"

# Проверить квоты в Google Cloud Console
# https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com
```

### Прокси не запускается

```bash
# Проверить логи
sudo journalctl -u gemini-proxy -n 50

# Проверить конфиг
cat /etc/gemini-proxy/config.env

# Запустить вручную для отладки
cd /opt/gemini-proxy
source venv/bin/activate
python gemini_proxy.py
```

### AI-управление не работает

Убедитесь, что:
1. `GEMINI_API_KEY` установлен и валиден
2. Модель `gemini-2.5-flash-preview-05-20` доступна для вашего ключа
3. Есть подключённые CLI-клиенты (проверьте `/v1/remote/clients`)

---

## Безопасность

1. **Смените `PROXY_API_KEY`** на сложный пароль
2. Используйте HTTPS (nginx reverse proxy + Let's Encrypt)
3. Ограничьте доступ по IP через firewall
4. Не храните Gemini API ключ в открытом виде — используйте secrets manager

```nginx
# Пример nginx конфига
server {
    listen 443 ssl;
    server_name gemini.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/gemini.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/gemini.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```
