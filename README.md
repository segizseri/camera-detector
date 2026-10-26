# Camera Detector AI Box

Локальная система видеоаналитики для ноутбука или небольшого edge-сервера. Проект подключается к существующему NVR/DVR по RTSP, показывает камеры в браузере через HLS и запускает локальную аналитику на базе YOLOv8-Pose + LSTM.

Проект ориентирован на Hikvision, но содержит базовый generic/Dahua-подобный RTSP-шаблон.

## Возможности

- Импорт камер из NVR через веб-интерфейс.
- Проверка RTSP-потока через `ffprobe`.
- HLS-просмотр камер в браузере.
- Локальная AI-аналитика по позам человека.
- Детекция действий: драка, буллинг, кража у кассы, кража с витрины, поедание/распитие у витрины.
- ROI-зоны для кассы и витрины.
- Линии подсчета пассажиров для дверей.
- События со снапшотами и короткими клипами.
- HTTP и Telegram webhooks.
- Реестр посетителей/Re-ID по лицам, если зависимости FaceNet успешно загрузились.
- Группировка камер по автобусам.
- Локальное дообучение LSTM-модели на собственных видео.
- Проверка детекций на загруженном видео или по ссылке YouTube с размеченным результатом и таймкодами.
- Basic Auth для веб-панели, API и медиа.
- Автоостановка HLS `ffmpeg`-процессов без активного просмотра.
- Автоочистка старых событий и медиа по `retention_days`.
- Базовые системные метрики через API.

## Архитектура

```text
camera-detector/
├── apps/api/          # FastAPI, HTML UI, REST API
├── apps/worker/       # RTSP ingest, YOLO, LSTM, события, клипы
├── libs/              # SQLAlchemy-модели, правила, webhooks, настройки
├── scripts/           # обучение ActionLSTM
├── infra/             # Dockerfile для api и worker
├── data/              # локальная БД, HLS, снапшоты, клипы, датасеты
└── docker-compose.yml
```

Сервисы:

- `api`: веб-панель и REST API, наружный порт `4000`, внутренний порт `8000`.
- `worker`: обработка камер, AI inference, события и клипы.
- База данных по умолчанию: SQLite `data/sqlite/laptop_ai_box.db`.

## Безопасность

Веб-панель, API и `/media` защищены Basic Auth, если `AUTH_ENABLED=true`. В обычном `docker-compose.yml` авторизация включена по умолчанию.

Переменные:

```bash
AUTH_ENABLED=true
ADMIN_USER=admin
ADMIN_PASS=admin
```

Перед реальным использованием измените `ADMIN_PASS`:

```bash
ADMIN_PASS='strong-local-password' docker compose up -d --build
```

Не открывайте порт `4000` в интернет. Для внешнего доступа используйте VPN или reverse proxy с HTTPS.

Новые NVR-камеры сохраняются в БД с RTSP URL без `user:password@`. Логин хранится отдельно, пароль шифруется через `ENCRYPTION_KEY` и подставляется только в момент подключения worker/ffmpeg. При старте API старые записи с credentials внутри `rtsp_url` автоматически мигрируются в этот формат, если ключ шифрования доступен.

## Быстрый запуск

### 1. Установка Docker на Ubuntu 22.04/24.04

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

arch="$(dpkg --print-architecture)"
codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
echo \
  "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${codename} stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker "$USER"
```

После добавления пользователя в группу `docker` нужно перелогиниться или выполнить `su - "$USER"`.

### 2. Запуск проекта

```bash
cd /home/user/projects/camera-detector
docker compose up -d --build
```

Откройте панель:

```text
http://localhost:4000
```

По умолчанию логин/пароль: `admin` / `admin`. Для реального запуска обязательно задайте свой `ADMIN_PASS`.

При первом запуске worker может скачать веса YOLO (`yolov8n-pose.pt`) и FaceNet-модели. Это занимает время и требует доступа к сети.

Логи:

```bash
docker compose logs -f
```

Остановка:

```bash
docker compose down
```

## Подключение Hikvision NVR

1. На NVR включите RTSP.
2. Создайте отдельного пользователя, например `ai_box`, с правами только на Live View.
3. Откройте `http://localhost:4000/nvr`.
4. Укажите IP, порт RTSP, логин, пароль и число каналов.
5. Для AI рекомендуется `Substream`: он снижает нагрузку на CPU.
6. Нажмите `Test Connection`, затем `Discover` или `Import Cameras`.

RTSP-шаблоны Hikvision:

```text
Main stream: rtsp://user:password@IP:554/Streaming/Channels/{channel}01
Substream:   rtsp://user:password@IP:554/Streaming/Channels/{channel}02
```

Для паролей со спецсимволами используйте URL-encoding. Например, `@` должен быть передан как `%40`.

## Тестовая среда

В проект добавлена отдельная тестовая среда, которая не использует боевую папку `data/`. Все тестовые данные пишутся в `data-test/`.

Она поднимает:

- локальный RTSP server `mediamtx`;
- publisher на `ffmpeg`, который генерирует fake RTSP-потоки;
- тестовый `api` на порту `4100`;
- тестовый `worker`;
- seed-скрипт, который по умолчанию создает 2 тестовые камеры.

Запуск:

```bash
docker compose -f docker-compose.test.yml up -d --build
```

Открыть тестовую панель:

```text
http://localhost:4100
```

В `docker-compose.test.yml` авторизация отключена (`AUTH_ENABLED=false`), чтобы smoke-тесты и тестовая панель запускались без логина. В обычном `docker-compose.yml` auth включен.

RTSP-потоки внутри тестовой сети имеют вид:

```text
rtsp://rtsp:8554/cam1
rtsp://rtsp:8554/cam2
```

С хоста первый поток можно проверить так:

```bash
ffplay rtsp://localhost:8554/cam1
```

Количество fake-камер можно менять:

```bash
TEST_CAMERA_COUNT=5 docker compose -f docker-compose.test.yml up -d --build
```

По умолчанию seed создает 2 камеры с `ai_enabled=false` и `fps_limit=2`. Это удобно, чтобы сначала проверить RTSP/HLS/браузер без нагрузки YOLO. Для проверки AI на двух камерах:

```bash
TEST_AI_ENABLED=true TEST_CAMERA_FPS=1 docker compose -f docker-compose.test.yml up -d --build
```

### Реальные интернет-видео и YouTube

Fake-потоки полезны для проверки нагрузки, но для AI лучше прогонять реальные сцены. Тестовый RTSP publisher поддерживает `TEST_SOURCE_URLS`: список HTTP/HTTPS/YouTube URL через запятую. Он берет источник, перекодирует его в локальный RTSP и публикует как `cam1`, `cam2`, ...

Пример с двумя YouTube-ссылками:

```bash
TEST_CAMERA_COUNT=2 \
TEST_SOURCE_URLS='https://www.youtube.com/watch?v=VIDEO_ID_1,https://www.youtube.com/watch?v=VIDEO_ID_2' \
docker compose -f docker-compose.test.yml up -d --build
```

Пример с одной ссылкой, размноженной на 5 тестовых камер:

```bash
TEST_CAMERA_COUNT=5 \
TEST_SOURCE_URLS='https://www.youtube.com/watch?v=VIDEO_ID' \
docker compose -f docker-compose.test.yml up -d --build
```

Настройки нормализации потока:

```bash
TEST_VIDEO_FPS=10
TEST_SOURCE_SCALE='640:-2'
```

Для проверки AI на реальном видео:

```bash
TEST_CAMERA_COUNT=2 \
TEST_AI_ENABLED=true \
TEST_CAMERA_FPS=1 \
TEST_SOURCE_URLS='https://www.youtube.com/watch?v=VIDEO_ID_1,https://www.youtube.com/watch?v=VIDEO_ID_2' \
docker compose -f docker-compose.test.yml up -d --build
```

YouTube-ссылки обрабатываются через `yt-dlp`. Если YouTube временно блокирует или меняет формат выдачи, обновите test publisher image:

```bash
docker compose -f docker-compose.test.yml build --no-cache rtsp-publisher
```

Используйте только видео или live-потоки, которые вы имеете право использовать для тестирования.

Повторно пересоздать тестовые камеры:

```bash
docker compose -f docker-compose.test.yml run --rm seed-test-cameras
```

Остановка тестовой среды:

```bash
docker compose -f docker-compose.test.yml down
```

Полная очистка тестовых данных:

```bash
docker compose -f docker-compose.test.yml down
rm -rf data-test
```

### Автоматические тесты

Запуск pytest в контейнере:

```bash
docker compose -f docker-compose.test.yml run --rm tests
```

Текущий smoke-набор проверяет:

- API списка/обновления камер;
- что HLS endpoint переиспользует уже запущенный `ffmpeg`-процесс для камеры;
- что API не возвращает RTSP-пароли;
- что runtime RTSP URL собирается с зашифрованным паролем только внутри;
- что retention удаляет старые события и медиа;
- базовую логику пересечения линии пассажирского счетчика.

## Основные страницы

- `/` - dashboard.
- `/nvr` - импорт камер из NVR.
- `/cameras` - список камер.
- `/cameras/{id}` - просмотр камеры, настройки AI, ROI-зоны и линии подсчета.
- `/ai` - обзор AI-операций.
- `/finetune` - сбор кадров и запуск обучения.
- `/visitors` - посетители и Face Re-ID.
- `/events-page` - события.
- `/reports/passengers` - пассажирские отчеты.
- `/integrations/webhooks` - HTTP/Telegram webhooks.
- `/settings` - глобальные настройки.
- `/buses` - автобусы и привязка камер.
- `/detection-test` - офлайн-проверка детекций на YouTube-ссылке или загруженном видео.

## Проверка детекций на видео

Откройте `/detection-test`, выберите источник и нужные детекторы, затем запустите анализ. Поддерживаются:

- ссылки `youtube.com`, `youtu.be` и `youtube-nocookie.com`;
- загрузка MP4, MOV, AVI, MKV, WebM и M4V;
- детекции драки, буллинга, кражи, кражи из витрины и поедания у витрины;
- подсчет пересечений горизонтальной пассажирской линии по центру кадра.

API сохраняет задание в общей SQLite, а `worker` скачивает или открывает видео, запускает тот же YOLOv8-Pose + ActionLSTM-конвейер и создает размеченный MP4. На странице отображаются прогресс, найденные события, confidence, снимки и переход к таймкоду.

Офлайн-проверка не знает ROI конкретной камеры: классы действий анализируются по всему кадру. На боевой камере фильтры зон кассы и витрины продолжают применяться как обычно.

Завершенные и ошибочные задания вместе с исходными/размеченными файлами удаляются общей retention-очисткой после `retention_days`.

Для запуска нужна обученная общая модель `data/models/action_lstm.pt`. Если файла нет, страница покажет статус «Модель не обучена» и не позволит запустить случайные необученные веса. YouTube загружается через `yt-dlp`, который входит в worker image.

В списке моделей также появляется `Eating-кандидат`, если существует `data/models/action_lstm_eating.pt`. Он предназначен для безопасной офлайн-проверки классов `Normal/Eating` и не заменяет общую модель остальных детекций.

Ограничения можно менять переменными окружения:

```bash
DETECTION_TEST_MAX_UPLOAD_MB=1024
DETECTION_TEST_MAX_DURATION_SECONDS=3600
```

После добавления функции пересоберите worker, чтобы установить `yt-dlp`:

```bash
docker compose up -d --build api worker
```

## AI-модель действий

Worker использует YOLOv8-Pose для извлечения 17 ключевых точек человека и `ActionLSTM` для классификации последовательности из 30 кадров.

Текущие классы:

| ID | Класс | Событие |
|---:|---|---|
| 0 | Normal | событие не создается |
| 1 | Fight | `fight_suspected` |
| 2 | Bullying | `bullying_suspected` |
| 3 | Theft | `theft_suspected` |
| 4 | Shoplifting | `shoplifting_suspected` |
| 5 | Eating | `eating_suspected` |

Если файл `action_lstm.pt` отсутствует, worker запускает LSTM с необученными весами. Для реальной аналитики модель нужно обучить на собственных данных.

## ROI-зоны

На странице камеры (`/cameras/{id}`) можно нарисовать:

- `Зона Кассы`: красный полигон для `theft_suspected`.
- `Зона Витрины`: голубой полигон для `shoplifting_suspected` и `eating_suspected`.
- `Перед. дверь` и `Зад. дверь`: линии для пассажирского счетчика.

Координаты сохраняются в БД как нормализованный JSON.

## Обучение LSTM на своих видео

Подготовьте структуру:

```text
data/dataset/
├── 0_normal/
├── 1_fight/
├── 2_bullying/
├── 3_theft/
├── 4_shoplifting/
└── 5_eating/
```

Разложите короткие `.mp4` ролики по соответствующим папкам. Для снижения ложных срабатываний обязательно добавьте много обычных сцен в `0_normal`.

Извлечение скелетов:

```bash
docker compose exec worker python scripts/train_lstm.py --extract
```

Обучение:

```bash
docker compose exec worker python scripts/train_lstm.py --train
```

Или одной командой:

```bash
docker compose exec worker python scripts/train_lstm.py --extract --train
```

### Быстрый интернет-набор для smoke-обучения

Для проверки пайплайна можно скачать маленький публичный sample-набор:

```bash
docker compose -f docker-compose.test.yml run --rm api \
  python scripts/bootstrap_real_action_dataset.py --clear \
  --normal-count 4 --theft-count 4 --shoplifting-count 6
```

Он складывает клипы в тестовый volume `data-test/dataset/`:

- `0_normal` - normal/no-robbery клипы;
- `3_theft` - robbery/theft-like клипы;
- `4_shoplifting` - shoplifting sample GIF, конвертированный в MP4.

После этого обучение в тестовой среде:

```bash
docker compose -f docker-compose.test.yml stop worker
docker compose -f docker-compose.test.yml run --rm worker \
  python scripts/train_lstm.py --extract --train
docker compose -f docker-compose.test.yml up -d worker
```

Оценка на извлеченных последовательностях:

```bash
docker compose -f docker-compose.test.yml run --rm worker \
  python scripts/evaluate_action_lstm.py
```

После обучения перезапустите worker:

```bash
docker compose restart worker
```

Новые веса сохраняются в `data/models/action_lstm.pt`.

Если реальный датасет еще не извлечен в `data/dataset/X.npy` и `data/dataset/y.npy`, скрипт откажется обучаться. Синтетические данные включаются только вручную через `--synthetic` и нужны только для developer smoke-тестов, не для реальной детекции.

### Тестовый кандидат для класса Eating

Для класса `5_eating` подготовлен отдельный исследовательский кандидат на основе
[Indoor Action Dataset](https://github.com/DaniDeniz/IndoorActionDataset) (BSD-3-Clause):

- train: 57 eating-клипов и 95 hard-negative/normal клипов;
- validation: 18 eating и 24 normal/hard-negative клипа;
- test: 32 eating и 47 normal/hard-negative клипов;
- извлечение поз: 5 FPS, YOLO-Pose `imgsz=320`, последовательность 30 кадров;
- целевой pose-фильтр: рука рядом с лицом минимум на 40% кадров;
- обучение: 10 эпох, сбалансированный sampler для `Normal` и `Eating`.

Команда целевого обучения после извлечения train и validation:

```bash
docker compose -f docker-compose.test.yml run --rm worker \
  python scripts/train_lstm.py --train \
  --focus-class 5 \
  --min-near-face-frac 0.4 \
  --extra-dataset-dir data/evaluation/indoor_action/validation \
  --save-path data/models/action_lstm_eating.pt \
  --epochs 10
```

Зафиксированный результат на независимом test split при runtime-пороге `0.55`:

| Accuracy | Precision Eating | Recall Eating | F1 Eating | TP | FP | FN | TN |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 72.22% | 80.00% | 63.16% | 70.59% | 24 | 6 | 14 | 28 |

Исходный кандидат хранится в тестовом контуре как `data-test/models/action_lstm_eating.pt`. Копия `data/models/action_lstm_eating.pt` используется только как выбираемый вариант на странице офлайн-проверки и не заменяет общую production-модель `data/models/action_lstm.pt` в камерах. Его качество пока недостаточно для автономного боевого оповещения; перед включением на боевом потоке нужны видео с реальных витрин и дополнительная проверка.

## Webhooks

Поддерживаются два режима:

- `http`: POST JSON на указанный URL с HMAC-SHA256 подписью в заголовке `X-Signature`.
- `telegram`: отправка сообщения или фото через Telegram Bot API.

Тест webhook доступен на странице `/integrations/webhooks`.

Текущая реализация отправляет webhooks в отдельном потоке. Модель `WebhookDelivery` есть в БД, но полноценная очередь retry/status пока не реализована.

## Troubleshooting

### Черный экран или нет HLS

Проверьте:

```bash
docker compose logs -f api worker
ls -la data/media/hls/
```

Также проверьте RTSP-поток в VLC или через страницу `/cameras`.

### RTSP не подключается

- Ноутбук должен иметь сетевой доступ к NVR.
- Обычно нужен исходящий доступ с ноутбука к NVR на TCP `554`.
- Для веб-панели клиентам нужен доступ к ноутбуку на TCP `4000`.
- Проверьте, что пользователь NVR имеет право Live View.
- Попробуйте substream вместо main stream.

### Высокая нагрузка CPU

- Используйте substream.
- Снизьте FPS обработки камеры.
- Отключите лишние детекторы на странице камеры.
- Ограничьте число одновременно включенных камер.

### 10-15 камер на mini PC

Для 15 камер это нормальная схема подключения, но mini PC обычно не сможет одновременно:

- читать 15 RTSP-потоков;
- запускать YOLO/LSTM по всем потокам с высоким FPS;
- транскодировать много HLS-видео для браузера;
- показывать несколько live-видео одновременно.

Рекомендуемые стартовые настройки:

- импортировать камеры через `Substream`;
- поставить `fps_limit` 1-3 для AI на каждую камеру;
- оставить `ai_enabled=true` только на камерах, где реально нужна аналитика;
- временно отключить тяжелые детекторы на второстепенных камерах;
- не открывать одновременно много страниц `/cameras/{id}` с live-видео;
- смотреть логи и нагрузку через `docker compose logs -f worker`.

Если браузер начинает зависать после просмотра разных камер, проверьте количество `ffmpeg`:

```bash
ps aux | grep ffmpeg | grep -v grep
```

HLS-процессы автоматически останавливаются после простоя. Таймаут настраивается:

```bash
HLS_IDLE_TIMEOUT_SECONDS=180
```

Для слабого CPU лучше начать с 3-5 камер с AI, затем постепенно включать остальные.

### Много клипов и снапшотов

Медиа сохраняются в:

```text
data/media/snapshots/
data/media/clips/
data/media/hls/
```

Worker периодически удаляет события, снапшоты, клипы и старые HLS-сегменты старше `retention_days`.

Интервал проверки:

```bash
RETENTION_SWEEP_INTERVAL_SECONDS=3600
```

Ручной запуск очистки:

```bash
curl -u admin:admin -X POST http://localhost:4000/api/system/cleanup
```

Базовые метрики:

```bash
curl -u admin:admin http://localhost:4000/api/system/metrics
```

## Известные ограничения MVP

- Basic Auth не заменяет полноценные роли, audit log и HTTPS.
- SQLite подходит для небольшой локальной установки; для высокой нагрузки лучше PostgreSQL.
- HLS все еще нагружает CPU и дает задержку. Для большого live-мониторинга лучше планировать WebRTC/RTSP proxy.
- Миграции БД выполняются при старте API через `create_all` и простые `ALTER TABLE`; Alembic не используется.
- Webhook retry/status delivery не реализован.
- AI-модель действий требует обучения на реальных данных с ваших камер, иначе будут ложные срабатывания.
- Тестовый набор пока покрывает только smoke/API и часть rule-логики.

## Проверка состояния

```bash
docker compose ps
docker compose logs -f worker
docker compose logs -f api
curl -u admin:admin http://localhost:4000/api/system/metrics
```

При изменении настроек камеры worker синхронизирует параметры из БД примерно раз в 10 секунд. Если RTSP URL изменился, перезапускается только pipeline этой камеры.
