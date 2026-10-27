# Разработка интерфейса

[На главную](../index.md) · [English](../../en/development/frontend.md)

Клиент находится в `apps/frontend/`. Это React и TypeScript с Vite. Вход выполняется из Telegram-бота; сервер проверяет данные запуска и выдаёт сессию. Токен бота используется только сервером.

## Запуск и сборка

Для разработки нужны Node.js 24.13.0 и запущенный API из [инструкции сервера](backend.md).

Из корня репозитория:

```sh
npm --prefix apps/frontend ci --ignore-scripts
npm --prefix apps/frontend run dev
```

Vite открывает интерфейс на `http://127.0.0.1:5173` и передаёт запросы `/api` серверу на `http://127.0.0.1:8000`. Вход сотрудника осуществляется через HTTPS-адрес приложения в Telegram. Для размещения используется [установщик](hosting.md).

```sh
npm --prefix apps/frontend run build
```

Сборка проверяет TypeScript и создаёт файлы в `apps/frontend/dist/`. Таймер обновляется локально, а состояние перечитывается после действия, возврата в приложение и смены даты.

## Каталоги

| Путь внутри `apps/frontend/src/` | Содержимое |
| --- | --- |
| `app/` | Оболочка, навигация и общие стили |
| `features/day/` | День, отметки и подтверждение ухода |
| `features/profile/` | Первый запуск и настройки |
| `features/statistics/` | Личная статистика |
| `features/admin/` | Пользователи, доступ и индивидуальный учёт |
| `shared/api/` | Запросы и типы API |
| `shared/api/generated/` | Типы из серверного OpenAPI |
| `shared/ui/` | Общие элементы интерфейса |
| `shared/lib/` | Время и интеграция Telegram |

## Контракт и проверки

Типы генерируются из работающего кода FastAPI:

```sh
uv run --project apps/backend python scripts/export_api.py
npm --prefix apps/frontend run generate:api
```

Сгенерированные файлы проверяются вместе с изменением API. Вручную они не редактируются.

```sh
npm --prefix apps/frontend run check:format
npm --prefix apps/frontend test
npm --prefix apps/frontend run test:browser
```

Браузерные проверки используют установленный Google Chrome и тестовые ответы API. Они проверяют первый запуск без автоматического прихода, указание более раннего времени, повтор запроса после обрыва связи, подтверждение забытого ухода и управление пользователями. Серверные проверки выполняют эти операции с настоящей PostgreSQL. Узкий экран проверяется на ширине 320 пикселей.
