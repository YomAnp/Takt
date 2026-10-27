# Takt

Telegram Mini App для личного учёта рабочего времени сотрудников МГРИ: приход, уход, перерывы и статистика.

[Документация](docs/ru/index.md) · [English](docs/en/index.md)

## Запуск

На сервере с Ubuntu или Debian нужны Git, Python 3.10+ и Docker с плагином Compose. [Подготовка сервера](docs/ru/development/hosting.md).

Создайте бота через [BotFather](https://t.me/BotFather). Направьте домен на сервер и откройте порты 80 и 443.

```sh
git clone https://github.com/YomAnp/Takt.git
cd Takt
python3 scripts/host.py setup
```

Введите домен, токен бота и свой `@username` в Telegram. Установщик соберёт приложение, запустит контейнеры, настроит HTTPS и кнопку бота.

После установки отправьте боту `/start` и нажмите «Открыть Такт».

## Обновление

В папке проекта:

```sh
git pull --ff-only
python3 scripts/host.py up
```
