# AI-движок детекций: публичный контракт

Статус: проект контракта, версия `0.1` (до `1.0` возможны несовместимые изменения).
Код контракта: [`detector_core/contract/`](../detector_core/contract/), JSON Schema и эталонный каталог: [`docs/schemas/`](schemas/), примеры: [`docs/schemas/examples/`](schemas/examples/), тесты: [`tests/test_detector_contract.py`](../tests/test_detector_contract.py).

Схемы генерируются из pydantic-моделей и проверяются тестом на актуальность:

```bash
python -m detector_core.contract.schema_export docs/schemas
```

## 1. Назначение и границы

Движок принимает видео (RTSP-поток, кадры через SDK или видеофайл), прогоняет по каждой камере **только выбранные на ней детекторы** и отдаёт события с жизненным циклом `started → updated → ended`. Он не знает ни про веб-интерфейс camera-detector, ни про его БД, поэтому его можно подключить к любой системе: к текущему приложению, к VMS, к системе магазина.

| Входит в движок | Остаётся в приложении (клиенте) |
|---|---|
| 5 детекторов: `fight`, `bullying`, `cash_theft`, `shelf_theft`, `eating` | Подсчёт пассажиров (`PassengerCounter`, `buses`, `passenger_counts`, `counting_config`, `detect_passengers`) |
| Общие компоненты: поза, трекер, модель взаимодействия, детектор предметов, приём POS | Распознавание лиц и посетители (`Visitor`, MTCNN/InceptionResnet), CRM |
| Каталог детекторов, конфиги камер, валидация входов | Учётные записи NVR, шифрование паролей, UI, HLS-превью |
| События, снимки и клипы инцидентов, доставка (webhook/MQTT/WebSocket) | Хранение событий в своей БД, Telegram-уведомления, русские подписи на кадрах |
| Пакетный режим «видео → события» | Скачивание YouTube-роликов (`yt-dlp`) для тестов |
| Health, метрики, лицензии детекторов | Пользователи, авторизация в веб-интерфейсе |

Разделение кода:

- `detector_core/`: библиотека без БД и без веба. Запрещены импорты `libs`, `apps`, `fastapi`, `starlette`, `sqlalchemy`. `detector_core/contract/` зависит только от стандартной библиотеки и pydantic v2; `torch`, `ultralytics`, ONNX Runtime подключаются только в реализациях компонентов. Это проверяет тест.
- `apps/engine/`: сервис поверх `detector_core` (HTTP API, приём потоков, доставка событий). У него своё хранилище (конфиги камер, outbox доставки, медиа) и никогда не общая БД приложения.
- Текущее приложение (`apps/api`, `apps/worker`) становится первым клиентом: сначала через SDK в том же процессе, потом через HTTP API.

Термины:

- **Детектор**: модуль, который решает одну задачу (например, «драка») и возвращает детекции по кадрам.
- **Компонент**: общая для детекторов модель или служба (поза, трекер…), загружается лениво.
- **Детекция** (`Detection`): сигнал детектора на одном кадре.
- **Событие** (`Event`): сообщение об инциденте, собранное движком из детекций, с фазами `started/updated/ended`.
- **Зона** (`Zone`): полигон в долях кадра (0..1) с типом (`cash_drawer`, `display`, `include`, `exclude`).

## 2. Пять детекторов

Сводка (эталонные объявления в [`catalog.py`](../detector_core/contract/catalog.py), JSON в [`schemas/catalog.json`](schemas/catalog.json)):

| id | Что ищет | Компоненты | Обязательные входы | legacy event_type | Зрелость |
|---|---|---|---|---|---|
| `fight` | обоюдная драка 2+ человек | pose, tracker, interaction_model | ≥ 5 кадров/с, человек ≥ 15 % высоты кадра | `fight_suspected` | prototype |
| `bullying` | длительная односторонняя агрессия против одного | pose, tracker, interaction_model | ≥ 5 кадров/с, ≥ 15 % | `bullying_suspected` | prototype |
| `cash_theft` | доступ к денежному ящику без подтверждения в POS | pose, tracker, pos_ingest | зона `cash_drawer`, поток POS, ≥ 5 кадров/с, ≥ 25 % | `theft_suspected` | concept |
| `shelf_theft` | взял товар с витрины и спрятал | pose, tracker, object_detector | зона `display`, ≥ 5 кадров/с, ≥ 20 % | `shoplifting_suspected` | concept |
| `eating` | ест или пьёт товар у витрины | pose, tracker, object_detector | зона `display`, ≥ 5 кадров/с, ≥ 20 % | `eating_suspected` | concept |

Зрелость (`maturity`): `concept`: контракт объявлен, реализации по нему ещё нет; `prototype`: реализация есть, качество на реальных данных не измерено; `beta`: измерено, есть operating envelope; `stable`.

Все версии сейчас `0.1.0`. Пороги и паузы по умолчанию взяты из текущего `AIActionDetector` (тест сверяет их с `libs/rules.py`).

### Общие параметры жизненного цикла (есть у каждого детектора)

| Параметр | fight | bullying | cash_theft | shelf_theft | eating | Смысл |
|---|---|---|---|---|---|---|
| `threshold` | 0.6 | 0.6 | 0.5 | 0.55 | 0.55 | детекция со `score ≥ threshold` активна (бывшие `thresholds`) |
| `min_duration_s` | 1.5 | 8 | 1.0 | 0.5 | 1.0 | сколько держится сигнал до `started` |
| `end_after_s` | 5 | 10 | 5 | 5 | 10 | тишина, после которой уходит `ended` |
| `cooldown_s` | 20 | 30 | 40 | 30 | 30 | пауза после `ended` (бывшие `cooldowns`) |
| `update_interval_s` | 5 | 5 | 5 | 5 | 5 | не чаще одного `updated` |
| `max_duration_s` | 600 | 600 | 600 | 600 | 600 | принудительное закрытие длинного инцидента |

### 2.1 `fight`: драка

- **Логика.** `interaction_model` оценивает агрессию для пар и групп треков; детектор поднимает детекцию, когда агрессия обоюдная и участников не меньше `min_participants`. Ключ инцидента: по умолчанию один инцидент на камеру, как сейчас.
- **Параметры.** `min_participants` (int, 2).
- **Выход.** `subjects[].role = participant`; `attributes`: `participants` (integer), `intensity` (number 0..1).
- **Operating envelope.** Ракурс сверху под углом или на уровне глаз, до ~15 человек в кадре, без плотной толпы. Модель обучена на 5 кадрах/с, окно 30 кадров (6 с).
- **Сейчас в коде.** Класс 1 `ActionLSTM` (`libs/ai_models.py`): классификатор последовательности позы **одного** человека, 30 кадров × 17 точек, 6 классов, сглаживание голосованием по 15 кадрам. Модели взаимодействия пар нет; на первом этапе миграции per-person LSTM служит временной реализацией `interaction_model`. Данные обучения в основном синтетические (`scripts/train_lstm.py`).

### 2.2 `bullying`: буллинг

- **Логика.** Тот же `interaction_model`, что у драки (компонент грузится один раз). Сверху правила: агрессия **односторонняя** (`one_sided_ratio`), длится не меньше `min_duration_s` (по умолчанию 8 с), нападающих не меньше `min_aggressors`, жертв не больше `max_targets`; люди рядом без участия (круг зрителей) повышают уверенность (`count_onlookers`).
- **Параметры.** `one_sided_ratio` (0.7), `min_aggressors` (1), `max_targets` (1), `count_onlookers` (true).
- **Выход.** `subjects[].role ∈ {aggressor, target, onlooker}`; `attributes`: `duration_s`, `one_sided_ratio`, `onlookers`.
- **Сейчас в коде.** Класс 2 той же LSTM; правил длительности и окружения нет.

### 2.3 `cash_theft`: кража из кассы

- **Логика.** Поза и трекер дают руку в зоне денежного ящика. `pos_ingest` даёт события кассы, привязанной к камере. Доступ к ящику легитимен, если в окне `pos_match_window_s` есть подходящее POS-событие. Причины тревоги (`reason`): `access_without_transaction`, `no_sale_access` (при `alert_on_no_sale`), `card_payment_access` (ящик при оплате картой, `alert_on_card_payment`), `access_after_void`.
- **Обязательные входы.** Зона `cash_drawer` (бывшая `theft_zone`, без потерь), `external_sources.pos` (идентификатор кассы), часы POS и NVR синхронизированы по NTP.
- **Параметры.** `pos_match_window_s` (10 с), `alert_on_no_sale` (true), `alert_on_card_payment` (true).
- **Выход.** `subjects[].role = actor`; `zone_ids`; `external_refs` (POS-события, на которые опирается решение); `attributes`: `reason`, `drawer_zone_id`, `pos_transaction_id`, `operator_id`, `seconds_from_pos_event`.
- **Сейчас в коде.** Класс 3 LSTM («длительно вытянутая рука») плюс `theft_zone`: детекция засчитывается, если центр bbox действующего лица внутри полигона; полигон из < 3 точек означает «зоны нет, проверять везде». POS нет совсем. **Изменение поведения:** в контракте зона и POS обязательны, без них детектор не включится (см. вопросы в конце).

### 2.4 `shelf_theft`: кража с витрины

- **Логика.** Человек в зоне витрины, предмет (`object_labels`, по умолчанию `product`) в руке по данным `object_detector`, затем за `conceal_window_s` рука с предметом уходит к карману, сумке или под одежду и предмет пропадает.
- **Обязательные входы.** Зона `display` (бывшая `display_zone`, общая с `eating`, как сейчас).
- **Параметры.** `conceal_window_s` (3 с), `object_labels` (`["product"]`), `min_object_score` (0.35), `require_object` (true; false оставляет только позу, как в текущем прототипе).
- **Выход.** `subjects[].role = actor`; `attributes`: `display_zone_id`, `object_label`, `conceal_location` (`pocket|bag|clothing|unknown`), `grab_to_conceal_s`.
- **Сейчас в коде.** Класс 4 LSTM, обученный на синтетическом паттерне «запястья к витрине, затем быстро к бедру», плюс `display_zone`. Детектора предметов нет.

### 2.5 `eating`: поедание у витрины

- **Логика.** В зоне витрины предмет `food`/`drink` в руке не меньше `hand_to_mouth_min` раз за `window_s` подносится ко рту (запястье у носа по ключевым точкам).
- **Обязательные входы.** Зона `display`.
- **Параметры.** `object_labels` (`["food", "drink"]`), `hand_to_mouth_min` (2), `window_s` (30 с), `require_object` (true).
- **Выход.** `subjects[].role = actor`; `attributes`: `display_zone_id`, `object_label`, `hand_to_mouth_count`.
- **Сейчас в коде.** Класс 5 LSTM и отдельные веса `action_lstm_eating.pt` (пакетный режим, `model_key=eating`), плюс `display_zone`. Детектора предметов нет.

## 3. Каталог и выбор детекторов по камере

### 3.1 Каталог

`GET /v1/detectors` возвращает `DetectorCatalog` ([схема](schemas/detector_catalog.schema.json), [пример](schemas/catalog.json)). По каждому детектору: `id`, `version`, `title`, `description`, `maturity`, `event_type`, `legacy_event_type`, `requirements` (min_fps, recommended_fps, min_person_height_frac, нужные зоны, нужные внешние потоки, operating envelope), `components` (какие общие компоненты он подтягивает), `params` (имя, тип, дефолт, min/max, варианты, единицы, заголовок по-русски), `output_attributes` (поля `Event.attributes`) и `license_feature`.

Этого достаточно, чтобы внешняя система построила у себя такой же экран выбора: чекбокс на детектор, инструменты рисования только для нужных типов зон, форму параметров по `params` и подсказку, что ещё не настроено (по ответу валидации).

### 3.2 Конфигурация камеры

`CameraConfig` ([схема](schemas/camera_config.schema.json)) по форме `{camera_id, detectors: {id: {...}}}` плюс входы:

```json
{
  "camera_id": "store-12-checkout-3",
  "enabled": true,
  "source": {"url": "rtsp://10.0.12.20:554/Streaming/Channels/301", "transport": "tcp"},
  "fps": 5,
  "scene": {"typical_person_height_frac": 0.45, "camera_view": "overhead"},
  "zones": [
    {"id": "cash_drawer", "kind": "cash_drawer",
     "polygon": [[0.41, 0.62], [0.58, 0.62], [0.58, 0.81], [0.41, 0.81]]}
  ],
  "external_sources": {"pos": ["store-12/register-3"]},
  "detectors": {
    "cash_theft": {"params": {"pos_match_window_s": 15}},
    "fight": {"version": "0.1"}
  },
  "labels": {"store": "12"}
}
```

- `detectors`: только выбранные детекторы; ключ отсутствует или `enabled: false` = детектор выключен. Значение (`DetectorConfig`): `enabled`, `version` (ожидаемая `major.minor` или точная версия), `zone_ids` (ограничить детектор частью зон камеры), `params` (только отличия от дефолтов).
- `zones`: зоны камеры, общие для детекторов. Координаты в долях кадра `[0, 1]`, начало в левом верхнем углу, от 3 до 64 точек. Это тот же формат, что у текущих `theft_zone`/`display_zone`, поэтому перенос идёт без пересчёта.
- `fps`: частота анализа (бывший `fps_limit`), общая для всех детекторов камеры.
- `scene.typical_person_height_frac`: типичная высота человека в долях кадра. Её вводит монтажник или измеряет движок (см. 3.4).
- `external_sources`: привязка внешних потоков; сейчас только `pos`.
- `labels`: метаданные клиента, движок копирует их в каждое событие.
- Входные модели запрещают лишние поля: опечатка (`"enabeld": true`) даёт ошибку, а не молча выключенный детектор.

Ещё примеры: [витрина](schemas/examples/camera_config.display.json), [камера без детекторов](schemas/examples/camera_config.no_detectors.json).

### 3.3 Ленивая загрузка и выгрузка компонентов

Граф зависимостей компонентов (`COMPONENT_DEPENDENCIES`):

```
pose ← tracker ← interaction_model
object_detector           (независим)
pos_ingest                (независим)
```

Правила:

1. **Что держать в памяти:** `resolve_components(camera_configs, catalog)` возвращает объединение `components` всех включённых детекторов на всех включённых камерах, замкнутое по зависимостям. Отключённые камеры и детекторы, а также id вне каталога ничего не добавляют.
   - только `fight` → `{pose, tracker, interaction_model}`, детектор предметов не загружается;
   - `shelf_theft` + `eating` (на одной или на разных камерах) → `{pose, tracker, object_detector}`: детектор предметов один на всех;
   - камера без детекторов → `∅`.
2. **Что прогонять на кадре:** `camera_components(camera, catalog)` для каждой камеры отдельно. Детектор предметов загружен ради витрины в зале, но на кадрах кассовой камеры не запускается.
3. **Камера без включённых детекторов:** движок не открывает её поток и не запускает на ней AI (сейчас `apps/worker/ai.py` гоняет позу на каждой камере с `ai_enabled`, даже если все `detect_*` выключены).
4. **Изменение конфигурации:** движок считает новое множество и вызывает `diff_components(loaded, required)`. `to_load` загружается до активации детекторов (состояние детектора на камере `loading → active`). `to_unload` выгружается после `component_idle_unload_s` (по умолчанию 60 с), чтобы не перезагружать модели, пока оператор щёлкает чекбоксы.
5. **Состояние на камеру.** Трекер держит отдельное состояние на каждую камеру (веса позы общие). Детекторы создаются по экземпляру на пару (камера, детектор).
6. **Ошибка загрузки** компонента переводит зависящие детекторы в `error` со статусом в `/v1/cameras/{id}/status`; остальные детекторы камеры продолжают работать.

### 3.4 Валидация при включении

`validate_camera_config(camera, catalog) -> list[ConfigIssue]` ([схема](schemas/config_issue.schema.json)) проверяет только включённые детекторы. `error` блокирует включение детектора, `warning` пропускает его, но качество не гарантируется.

| code | severity | Когда |
|---|---|---|
| `unknown_detector` | error | id нет в каталоге движка |
| `version_mismatch` | error | `DetectorConfig.version` не совпадает с установленной |
| `zone_missing` | error | нет зоны нужного типа (с учётом `zone_ids`) |
| `unknown_zone` | error | `zone_ids` ссылается на несуществующую зону |
| `external_source_missing` | error | детектору нужен POS, а `external_sources.pos` пуст |
| `fps_too_low` | error | `fps < requirements.min_fps` |
| `person_too_small` | error | `scene.typical_person_height_frac < min_person_height_frac` |
| `person_size_unknown` | warning | размер человека не задан; движок измерит медиану высоты bbox на лету и сообщит в статусе камеры |
| `unknown_param` / `invalid_param` | error | параметр не из каталога, не тот тип, вне min/max, значения не из `choices` |

Пример ответа `PUT /v1/cameras/cam-1` для `cash_theft` без зоны ящика (HTTP 422, конфиг не применён):

```json
{
  "issues": [{
    "camera_id": "cam-1",
    "detector_id": "cash_theft",
    "code": "zone_missing",
    "severity": "error",
    "field": "zones",
    "message": "Детектору «Кража из кассы» нужна зона типа cash_drawer (минимум 1, найдено 0): нарисуйте полигон не меньше чем из 3 точек. Полигон денежного ящика (бывшая theft_zone).",
    "details": {"zone_kind": "cash_drawer", "min_count": 1, "found": 0}
  }]
}
```

Структурные ошибки (полигон из 2 точек, координата 1.2, лишнее поле) ловит сама схема (`ValidationError` → 422 с путём до поля).

## 4. Интерфейс детектора

Протокол [`Detector`](../detector_core/contract/detector.py), один экземпляр на пару (камера, детектор):

```python
class Detector(Protocol):
    info: DetectorInfo                      # элемент каталога
    id: str; version: str                   # = info.id, info.version
    requirements: Requirements              # = info.requirements
    components: frozenset[ComponentId]      # = info.components
    def configure(self, camera: CameraConfig, config: DetectorConfig) -> None: ...
    def process(self, frame: FrameContext) -> Sequence[Detection]: ...
    def on_external_event(self, event: ExternalEvent) -> Sequence[Detection]: ...
    def reset(self) -> None: ...            # переподключение потока, перемотка видео
```

`BaseDetector` выводит `id/version/requirements/components` из `info`. Плагины регистрируют `DetectorFactory` (`info` + `create(camera_id, components)`) через entry point `camera_detector.detectors`.

Гарантии движка:

- `configure()` вызывается до первого `process()` и при каждом изменении конфига, только если валидация не вернула ошибок; `config.params` уже дополнены дефолтами (`effective_params`).
- `process()` вызывается последовательно, из одного потока, `offset_s` растёт.
- В `FrameContext` заполнены выходы всех компонентов из `components` детектора.

Детектор **не** пишет в БД, не шлёт вебхуки, не сохраняет снимки и не держит веса общих компонентов. Он только возвращает `Detection`; события из них собирает движок (раздел 5).

[`FrameContext`](../detector_core/contract/frame.py) (dataclass, не сериализуется):

| Поле | Тип | Смысл |
|---|---|---|
| `camera_id`, `frame_index` | str, int | |
| `timestamp` | datetime UTC | время кадра; в пакетном режиме `recorded_at + offset_s` |
| `offset_s` | float | секунды от начала потока или видео |
| `fps` | float | фактическая частота анализа |
| `frame_size` | (w, h) | размер исходного кадра |
| `zones` | `Sequence[Zone]` | зоны, доступные детектору (с учётом `zone_ids`) |
| `persons` | `Sequence[PersonObservation] \| None` | bbox, score, track_id, 17 ключевых точек COCO `(x, y, conf)` |
| `objects` | `Sequence[ObjectObservation] \| None` | предметы: label, bbox, score |
| `interactions` | `Sequence[InteractionObservation] \| None` | агрессия по группам треков, доля инициатора |
| `image` | ndarray BGR \| None | кадр только для чтения |

Все координаты нормализованы в `[0, 1]`, как зоны. `None` означает, что компонент для этой камеры не загружен; пустой кортеж означает, что компонент отработал и ничего не нашёл. Для проверки зоны есть `point_in_polygon` (граница считается внутри, как `cv2.pointPolygonTest >= 0`).

`Detection` ([схема](schemas/detection.schema.json)): `detector_id`, `camera_id`, `timestamp`, `label` (например `hand_in_drawer`), `score`, `incident_key`, `bbox`, `subjects` (track_id + роль), `zone_id`, `external_refs`, `attributes`.

## 5. События

### 5.1 Сборка событий из детекций

Движок держит по одному автомату на ключ `(camera_id, detector_id, incident_key)`. `incident_key = null` означает один инцидент на детектор и камеру; так работает текущий cooldown, где `last_alerts` хранится на класс.

```
idle ──активная детекция──▶ pending ──доля активных кадров за min_duration_s ≥ 0.5──▶ open: started (seq=0)
open ──каждые update_interval_s или новый участник──▶ updated (seq+1)
open ──нет активных детекций дольше end_after_s──▶ ended (end_reason=inactive) ──▶ cooldown
open ──длительность ≥ max_duration_s──▶ ended (max_duration)
cooldown ──cooldown_s после ended_at──▶ idle
```

- Активная детекция: `score ≥ threshold`. В текущем pipeline порог сравнивается через `>`, в пакетном режиме через `>=`; контракт фиксирует `>=`.
- `confidence`: среднее `score` активных детекций за последние `min_duration_s`. `peak_confidence`: максимум `confidence` за инцидент.
- `subjects`, `zone_ids`, `external_refs`: объединение по детекциям инцидента. `attributes`: из последней активной детекции (детектор сам считает агрегаты вроде `duration_s`).
- Выключение детектора, остановка камеры и смена конфига закрывают открытые инциденты (`detector_disabled`, `camera_stopped`, `config_changed`). После падения движок при старте закрывает незакрытые инциденты с `engine_restart`. Каждый `started` рано или поздно получает `ended`.

### 5.2 Схема события

[`event.schema.json`](schemas/event.schema.json); примеры одного инцидента: [started](schemas/examples/event.fight.started.json), [updated](schemas/examples/event.fight.updated.json), [ended](schemas/examples/event.fight.ended.json).

| Поле | Смысл |
|---|---|
| `schema_version` | версия контракта, `"0.1"` |
| `event_id`, `seq` | id инцидента, общий для всех фаз; номер сообщения (у `started` 0) |
| `phase` | `started` / `updated` / `ended` |
| `detector_id`, `detector_version`, `event_type` | кто и что обнаружил |
| `camera_id`, `labels` | камера и метаданные клиента |
| `started_at`, `updated_at`, `ended_at` | начало; время последнего наблюдения в этом сообщении; конец (только в `ended`, это последняя активная детекция) |
| `end_reason` | `inactive`, `max_duration`, `camera_stopped`, `detector_disabled`, `config_changed`, `stream_end`, `engine_restart` |
| `confidence`, `peak_confidence` | текущая и максимальная уверенность |
| `subjects[]` | `track_id`, `role` (`actor`, `participant`, `aggressor`, `target`, `onlooker`), `bbox` |
| `zone_ids`, `external_refs[]` | зоны и внешние события (POS), на которые опирается решение |
| `media` | `snapshot_url` (с `started`), `clip_url` (с `ended`: 6 с до начала и до конца инцидента) |
| `attributes` | поля детектора из `output_attributes` |
| `source`, `start_offset_s`, `end_offset_s` | `live` или `batch`; смещения от начала видео в пакетном режиме |

Все времена с часовым поясом (UTC в выходах движка). Модель проверяет правила цикла: `started` имеет `seq=0`; `ended_at`/`end_reason` есть только у `ended`; `peak_confidence ≥ confidence`. Клиенты обязаны игнорировать неизвестные поля, поэтому модель `Event` их допускает.

### 5.3 Доставка

- Гарантия at-least-once. Дубликаты отсекаются по `(event_id, seq)`. Порядок сообщений одного `event_id` сохраняется в пределах одного получателя.
- Outbox на диске движка: доставка переживает перезапуск, повторы идут с экспоненциальной задержкой.
- Снимки и клипы хранит движок (`media_retention_days`, по умолчанию 7); клиент скачивает их к себе, если нужно хранить дольше.

## 6. Соответствие текущей схеме данных

| Сейчас | В контракте |
|---|---|
| `Camera.detect_fights` | `detectors.fight.enabled` |
| `Camera.detect_bullying` | `detectors.bullying.enabled` |
| `Camera.detect_theft` | `detectors.cash_theft.enabled` |
| `Camera.detect_shoplifting` | `detectors.shelf_theft.enabled` |
| `Camera.detect_eating` | `detectors.eating.enabled` |
| `Camera.theft_zone` (JSON `[[x,y],…]`) | `zones[] {id: "cash_drawer", kind: "cash_drawer"}` |
| `Camera.display_zone` (общая для 4 и 5) | `zones[] {id: "display", kind: "display"}`, общая для `shelf_theft` и `eating` |
| `Camera.fps_limit` | `fps` |
| `Camera.ai_enabled = false` | `enabled: false`, выбор детекторов сохраняется |
| `GlobalSetting fight_sensitivity` low/medium/high | `detectors.fight.params.threshold` 0.8 / 0.6 / 0.4 |
| `AIActionDetector.thresholds` / `cooldowns` | `params.threshold` / `params.cooldown_s` |
| Классы LSTM 1–5 | `fight`, `bullying`, `cash_theft`, `shelf_theft`, `eating` |
| `ACTION_META` ключи `theft`, `shoplifting` | `cash_theft`, `shelf_theft` |
| `fight_suspected`, …, `eating_suspected` | `DetectorInfo.legacy_event_type` |
| `Camera.detect_passengers`, `counting_config` | не переносятся, остаются в приложении |

Конвертер [`detector_core/legacy.py`](../detector_core/legacy.py) (`camera_config_from_legacy`) принимает строку `cameras` как словарь. Он сохраняет полигоны точка в точку, а координаты за краем кадра прижимает к `[0, 1]`. Полигоны из < 3 точек отбрасывает с пометкой, как и текущий pipeline. Тест сверяет маппинг с колонками `Camera` и ключами `DETECTORS` пакетного режима, поэтому новый `detect_*` без маппинга уронит тест.

## 7. API движка

Базовый путь `/v1`. Авторизация: API-ключ в `Authorization: Bearer …` (mTLS как опция для установки на объекте).

### 7.1 Каталог и камеры

| Метод | Путь | Что делает |
|---|---|---|
| GET | `/v1/detectors` | `DetectorCatalog` установленных детекторов |
| GET | `/v1/detectors/{id}` | `DetectorInfo` |
| GET | `/v1/components` | компоненты: `loaded`, число пользователей, память, бэкенд (onnxruntime/openvino/tensorrt) |
| GET | `/v1/cameras` | список `CameraConfig` (пароли скрыты) |
| PUT | `/v1/cameras/{camera_id}` | создать или заменить конфиг. 200: `{config, issues (warnings), active_detectors, components}`; 422: `{issues}`, конфиг не применён |
| POST | `/v1/cameras/{camera_id}/validate` | то же без применения (dry run для UI) |
| PATCH | `/v1/cameras/{camera_id}/detectors/{detector_id}` | включить, выключить или поменять параметры одного детектора (`DetectorConfig`) |
| DELETE | `/v1/cameras/{camera_id}` | удалить камеру; открытые инциденты закрываются `camera_stopped` |
| GET | `/v1/cameras/{camera_id}/status` | состояние потока, входной и фактический fps, задержка, потерянные кадры, состояние каждого детектора (`loading/active/error/blocked`), измеренная высота человека, нарушения envelope |

Политика частичной валидности: если у одного детектора камеры ошибка, `PUT` всё равно возвращает 422 и ничего не меняет. Так внешняя система не получит «молча» наполовину включённую камеру. Если клиент хочет включить только валидное, он присылает конфиг без проблемного детектора.

### 7.2 Внешние события (POS)

`POST /v1/external-events`: одно `ExternalEvent` или массив до 500 штук ([схема](schemas/external_event.schema.json), примеры: [no_sale](schemas/examples/external_event.pos_no_sale.json), [оплата картой](schemas/examples/external_event.pos_payment.json)). Ответ 202.

- Идемпотентность по `(kind, source_id, event_id)`.
- `occurred_at` обязательно с часовым поясом; наивное время отклоняется.
- Сумма передаётся в минимальных единицах (`amount_minor` + `currency`), без float.
- Движок маршрутизирует событие на все камеры, у которых `source_id` есть в `external_sources.pos`, и вызывает `on_external_event` у их детекторов. События хранятся в окне `max(pos_match_window_s)` плюс запас на опоздание доставки.
- Альтернативные транспорты `pos_ingest`: подписка MQTT `…/pos/{source_id}`; адаптеры конкретных кассовых систем вне контракта.

### 7.3 Выходы

- **Webhook.** `POST /v1/subscriptions {"type": "webhook", "url", "secret", "filter": {"camera_ids", "detector_ids", "phases"}}`. Тело: `Event`. Заголовки: `X-Event-Id`, `X-Event-Seq`, `X-Signature-Timestamp`, `X-Signature: sha256=HMAC_SHA256(secret, timestamp + "." + body)`. Метка времени в подписи защищает от повтора; это отличие от текущего `libs/webhooks.py`, который подписывает только тело. Ответ 2xx = доставлено.
- **MQTT.** Топик `camera-detector/v1/events/{camera_id}/{detector_id}`, QoS 1, retain=false, payload `Event`. Статус движка: retained-топик `camera-detector/v1/status` с LWT `offline`.
- **WebSocket.** `GET /v1/events/stream?camera_ids=…&detector_ids=…&phases=…&cursor=…`: по сообщению `Event` на кадр WebSocket. `cursor` позволяет продолжить после обрыва (движок держит буфер последних событий).
- **Pull.** `GET /v1/events?since=<cursor>&limit=…` для систем без входящих соединений.

### 7.4 Пакетный режим «видео → события»

| Метод | Путь | Что делает |
|---|---|---|
| POST | `/v1/jobs` | multipart-файл или `source_url` (http/https) + `{"detectors": {id: DetectorConfig}, "zones", "scene", "sample_fps", "recorded_at", "external_events": [...], "outputs": {"annotated_video": true, "snapshots": true}}` |
| GET | `/v1/jobs/{id}` | `status` (`queued/processing/completed/failed/cancelled`), `stage`, `progress`, `error` |
| GET | `/v1/jobs/{id}/events` | итоговые события: по одному `ended` на инцидент, `source=batch`, `start_offset_s/end_offset_s` ([пример](schemas/examples/event.cash_theft.batch.json)) |
| GET | `/v1/jobs/{id}/stats` | кадры, `max_people`, `frames_with_people`, активные кадры по детекторам |
| GET | `/v1/jobs/{id}/artifacts/annotated.mp4` | видео с разметкой |
| DELETE | `/v1/jobs/{id}` | отменить и удалить |

Тело задания по сути `CameraConfig` без `source`, поэтому валидация та же. `external_events` позволяет прогнать `cash_theft` по записи вместе с журналом кассы. Лимиты длительности и размера настраиваются (сейчас `DETECTION_TEST_MAX_DURATION_SECONDS`, `DETECTION_TEST_MAX_UPLOAD_MB`). Это замена текущего `DetectionTestRunner`. Его `results_json` (`events`, `event_count`, `max_people`, `frames_with_people`, `action_frame_counts`) переносится в `/events` и `/stats`; `passenger_counts` остаётся на стороне приложения.

### 7.5 Health и метрики

- `GET /healthz`: процесс жив. `GET /readyz`: загружены компоненты для всех активных детекторов, outbox не переполнен.
- `GET /metrics` (Prometheus): `engine_camera_up{camera}`, `engine_frames_processed_total{camera}`, `engine_frames_dropped_total{camera,reason}`, `engine_inference_seconds{component}` (histogram), `engine_component_loaded{component}`, `engine_detector_active{camera,detector}`, `engine_events_total{detector,phase}`, `engine_delivery_failures_total{sink}`, `engine_outbox_size`, `engine_envelope_violations_total{camera,detector,kind}`.

## 8. Версионирование

- **Контракт** (`CONTRACT_VERSION`, поле `schema_version` в сообщениях, префикс `/v1`). До `1.0` возможны несовместимые изменения. После `1.0` minor добавляет только необязательные поля, новые коды и значения enum; major означает новый префикс API, старый поддерживается не меньше одного релиза.
- **Детектор** (`DetectorInfo.version`, semver):
  - major: изменился смысл события, добавлен обязательный вход, удалён или переименован параметр, сменился тип поля `attributes`;
  - minor: новый необязательный параметр или поле `attributes`, заметно другая модель при том же смысле;
  - patch: переобученные веса без изменения контракта (с записью в changelog и метриками качества).
- Клиент может закрепить ожидаемую версию через `DetectorConfig.version` (`"0.1"` = любой `0.1.x`). При несовпадении будет `version_mismatch`, а не неожиданная смена поведения после обновления движка.
- Клиенты игнорируют неизвестные поля и неизвестные значения enum в выходах. Движок отклоняет неизвестные поля во входах.
- В одной установке движка одна версия каждого детектора. A/B сравнение весов делается вторым экземпляром движка или в пакетном режиме.

## 9. Поставка и рантаймы

Режимы поставки:

1. **Docker-образ движка** (`apps/engine`): CPU-образ (ONNX Runtime), Intel (OpenVINO), NVIDIA (TensorRT, в том числе Jetson). Конфиг и лицензия монтируются томом. Основной режим для внешних систем.
2. **Пакетный API**: тот же образ, только `/v1/jobs`. Подходит для разбора архивов и пилотов («пришлите видео — покажем события»).
3. **SDK**: Python-пакет `detector_core` с движком в процессе: `Engine(catalog, runtime).add_camera(CameraConfig)`, `engine.push_frame(camera_id, frame, ts)`, `engine.analyze_video(path, config) -> Iterator[Event]`. Через SDK текущее приложение подключается на первом этапе.
4. **Плагины VMS**: тонкий адаптер под конкретную VMS. Он передаёт движку RTSP-адреса и зоны из VMS и возвращает события в API событий VMS (тревоги, закладки на таймлайне). Движок при этом не меняется: адаптер говорит на том же `/v1`.

Рантаймы. Компоненты экспортируются PyTorch → ONNX и дальше в OpenVINO IR или TensorRT engine. Бэкенд выбирается на весь движок (`runtime: onnxruntime | openvino | tensorrt`), веса компонентов идут с sha256 в манифесте. Реализации компонентов, которым нужен `torch`, допустимы только на этапе миграции.

## 10. Лицензирование детекторов по отдельности

- У каждого детектора есть `license_feature` (`detector.fight` и т. д.).
- Лицензия: подписанный файл (Ed25519) со списком фич, лимитом камер на фичу, сроком и привязкой к установке. Движок проверяет подпись офлайн.
- Каталог показывает все установленные детекторы. Неоплаченный нельзя включить: валидация вернёт ошибку `license_required` (новый код в minor-версии контракта), а статус камеры покажет `blocked`.
- Общие компоненты не лицензируются отдельно: они подтягиваются оплаченными детекторами.
- Лимит считается по парам (камера, детектор). Камера с `fight` и `bullying` расходует по одному месту каждой фичи.

## 11. Риски

1. **AGPL-3.0 у `ultralytics`.** Код пакета `ultralytics` (YOLOv8, его трекеры ByteTrack/BoT-SORT, экспорт) и веса YOLOv8 распространяются под AGPL-3.0. Если поставлять движок закрытым продуктом или как сетевой сервис третьим лицам, нужен либо коммерческий Enterprise-лицензионный договор Ultralytics, либо замена. Кандидаты под Apache-2.0: RTMPose/RTMO (MMPose) для позы, RTMDet (MMDetection) или YOLOX для предметов. ByteTrack в исходной реализации под MIT, его можно переписать без `ultralytics`. Замена делается внутри компонентов `pose`/`tracker`/`object_detector` и не трогает контракт; именно поэтому детекторы получают выходы компонентов, а не объекты `ultralytics.Results`.
2. **Лицензии данных и весов.** Многие публичные наборы для драк, краж и действий (например RWF-2000, UCF-Crime, NTU RGB+D) выдаются только для исследований. Ролики с YouTube принадлежат их авторам, и лицензия репозитория-сборника этих прав не передаёт. `scripts/bootstrap_real_action_dataset.py` сейчас тянет `ZakiaYahya/Youtube-Robbery-Video-Dataset` и `1amitos1/Shoplifting-Detection`; их лицензии надо проверить до коммерческого использования обученных на них весов. Для каждого веса нужен манифест происхождения данных; для коммерческой поставки нужны собственные или лицензированные данные.
3. **Operating envelope.** Детектор корректен только в условиях, где его измеряли: ракурс, размер человека, fps, освещённость, плотность людей. Вне их он ошибается молча. Меры: `requirements.operating_envelope` в каталоге; проверка fps и размера человека при включении; измерение на лету (медиана высоты bbox, фактический fps, число людей) с метрикой `engine_envelope_violations_total` и статусом камеры; в продажах: «работает в описанных условиях», а не «распознаёт драки».
4. **Качество текущих моделей.** Все пять классов сейчас дают одна per-person LSTM, обученная в основном на синтетике. Зрелость в каталоге честно `prototype`/`concept`. До `beta` нужны размеченные реальные записи с объектов и метрики (precision/recall, ложные срабатывания на камеру в сутки).
5. **Синхронизация времени POS и видео.** Без NTP на кассе и NVR `cash_theft` даёт ложные срабатывания. Окно `pos_match_window_s` частично компенсирует рассинхрон, а движок должен показывать оценку рассинхрона в статусе.
6. **Персональные данные.** Снимки и клипы с людьми, треки, в приложении ещё и биометрия лиц. Движок не хранит лиц и идентичностей; медиа хранится ограниченный срок. Требования законодательства о персональных данных (РК, при экспорте GDPR) остаются на стороне интегратора и приложения.
7. **Производительность.** Ленивая загрузка экономит память, но не CPU. Детектор предметов на витринных камерах заметно дороже позы. Нужно ограничивать его зоной витрины и окрестностью рук и батчить инференс между камерами.

## 12. План миграции

Принципы: каждый шаг оставляет приложение рабочим, шаги 1–3 не меняют поведение для пользователя. Параллельная сессия сейчас правит `apps/worker/ai.py`, `apps/worker/pipeline.py`, `libs/rules.py`, `libs/ai_models.py`, `scripts/`, поэтому шаги, которые трогают эти файлы, начинаются после того, как её правки влиты.

0. **Контракт (сделано).** `detector_core/contract/`, JSON Schema, эталонный каталог, конвертер legacy, тесты контракта.
1. **Компоненты в `detector_core/components/`.** Перенести загрузку YOLO-позы и трекер с состоянием на камеру (`PersonPoseTracker`/`load_pose_model` из `libs/ai_models.py`) в `pose` и `tracker`, `ActionLSTM` во временную реализацию `interaction_model` и общую модель действий. Выходы приводятся к `PersonObservation`/`InteractionObservation`. В `libs/ai_models.py` и `libs/rules.py` остаются тонкие реэкспорты, чтобы приложение и скрипты обучения не сломались.
2. **Legacy-адаптеры детекторов в `detector_core/detectors/`.** Пять классов LSTM оборачиваются в `Detector` версии `0.0.x`. Их `info.components` честно перечисляет то, что они используют сейчас (`pose`, `tracker`, LSTM; без `object_detector` и `pos_ingest`). Проверка зон через `point_in_polygon` по центру bbox действующего лица, как в текущем pipeline. Эталонные объявления `0.1.0` из `contract/catalog.py` остаются целью для следующих версий.
3. **Сборщик событий и рантайм в `detector_core/engine/`.** `EventAssembler` (раздел 5.1) заменяет `last_alerts`/`cooldowns` в pipeline. `ComponentRegistry` со счётчиками ссылок, ленивой загрузкой и отложенной выгрузкой. `CameraRuntime` прогоняет `camera_components()` по кадру. `apps/worker` использует движок через SDK в том же процессе: `CameraPipeline` отдаёт кадры, а `_trigger_event` вызывается на `started` (одна строка `events` на инцидент, как сейчас, с `event_type = legacy_event_type`). На `ended` дописывается `clip_path` и `meta_json`. Камеры без детекторов перестают гонять позу.
4. **JSON-конфиг детекторов в БД.** Добавить колонку `cameras.detector_config` (Text, JSON `CameraConfig` без `source`). `auto_migrate` в `apps/api/main.py` добавит её сам; данные заполнит разовый скрипт на `camera_config_from_legacy` с отчётом по каждой камере (пропущенные полигоны, ошибки валидации). Дальше двойная запись на один релиз: `PATCH /api/cameras/{id}` пишет JSON и старые колонки, worker читает JSON. `camera_detail.html` строит чекбоксы, инструменты рисования зон и формы параметров по `GET /detectors` и показывает `issues` из валидации. Затем удалить `detect_fights`, `detect_bullying`, `detect_theft`, `detect_shoplifting`, `detect_eating`, `theft_zone`, `display_zone` из модели и `CameraUpdate`. Колонки в SQLite удаляются через `ALTER TABLE … DROP COLUMN` (SQLite ≥ 3.35) или пересборку таблицы. `detect_passengers` и `counting_config` остаются.
5. **Сервис `apps/engine/`.** FastAPI с API раздела 7, `infra/Dockerfile.engine`, сервис `engine` в `docker-compose.yml`, собственное хранилище (конфиги, outbox, медиа). Приложение становится сетевым клиентом: `PUT /v1/cameras` при сохранении камеры, приём событий по webhook или WebSocket, пакетный режим через `/v1/jobs` вместо `DetectionTestRunner`. Подсчёт пассажиров и распознавание лиц остаются в worker приложения (см. открытые вопросы про треки).
6. **Детекторы по контракту `0.1.0`.** Компоненты `object_detector` (RTMDet/YOLOX → ONNX), `pos_ingest`, обученная парная `interaction_model`. Детекторы переходят с `0.0.x` на реализации по эталонным объявлениям. Поза и трекер переходят на Apache-2.0-реализации, если решено уйти от AGPL.
7. **Уборка.** Удалить legacy-адаптеры, `AIActionDetector`, реэкспорты в `libs/`, `detector_core/legacy.py`.

## 13. Открытые вопросы

1. `cash_theft` без POS. Контракт делает POS обязательным, и камеры, где сейчас работает «кража из кассы» только по `theft_zone`, после миграции её потеряют. Оставить так или ввести деградированный режим (параметр, снимающий требование POS, с пометкой в событии)?
2. Камеры с включёнными `detect_theft`/`detect_shoplifting`/`detect_eating`, но без нарисованной зоны, сейчас ловят везде. В контракте зона обязательна. При миграции выключать такие детекторы с отчётом (предложение) или временно разрешать «зона = весь кадр»?
3. Подсчёт пассажиров и Re-ID лиц используют тот же проход YOLO, что и детекторы. После выноса приложению нужны треки людей: экспортировать из движка поток треков (`/v1/cameras/{id}/tracks`, дороже по трафику) или запускать в приложении свою позу (дороже по CPU)?
4. Лицензия на позу и трекер: покупать Ultralytics Enterprise или закладывать переход на RTMPose/RTMDet/YOLOX в шаг 6?
5. Пороги размера человека (15 / 25 / 20 % высоты кадра) и `min_fps = 5` взяты оценочно. Подтвердить на реальных камерах до `beta`. Тестовые камеры из `scripts/seed_test_cameras.py` идут с `TEST_CAMERA_FPS=2` и не пройдут валидацию.
6. `model_key` пакетного режима (`general`/`eating` веса): переносить как отдельные версии детектора `eating` или убрать после обучения общей модели?
7. Модель лицензирования: все пять детекторов платные отдельно или `fight` входит в базовую поставку (`license_feature = null`)?
8. Транспорт POS по умолчанию: HTTP push от кассовой системы или подписка MQTT? Какие кассовые системы нужны первыми?
