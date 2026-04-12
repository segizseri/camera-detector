#!/bin/bash

# Скрипт для быстрого запуска AI Box проекта

echo "🚀 Начинаем запуск Camera Detector AI Box..."

# Убедимся, что docker compose установлен и работает
if ! command -v docker compose &> /dev/null
then
    echo "❌ Ошибка: docker compose не установлен! Пожалуйста, установите Docker: https://docs.docker.com/engine/install/"
    exit 1
fi

echo "📦 Сборка и запуск контейнеров в фоновом режиме..."
docker compose up -d --build

# Проверяем успешность выполнения
if [ $? -eq 0 ]; then
    echo "--------------------------------------------------------"
    echo "✅ Приложение успешно запущено!"
    echo "🌐 Веб-панель доступна по адресу: http://localhost:4000"
    echo "🔐 Логин и пароль по умолчанию: admin / admin"
    echo "--------------------------------------------------------"
    echo "📄 Чтобы посмотреть логи в реальном времени, выполните:"
    echo "   docker compose logs -f"
    echo ""
    echo "🧠 Чтобы дообучить нейросеть (драк), выполните:"
    echo "   docker compose exec worker python scripts/train_lstm.py"
    echo "--------------------------------------------------------"
else
    echo "❌ Произошла ошибка при запуске. Проверьте логи Docker."
    exit 1
fi
