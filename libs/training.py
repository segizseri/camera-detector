"""Фоновое дообучение ActionLSTM со статусом и журналом для веб-интерфейса.

Запускается worker'ом по файлу-триггеру data/.trigger_train_lstm. Шаги:
  1. извлечение поз из роликов data/dataset/<класс>/*.mp4;
  2. оценочная модель с отложенными роликами (20% по каждому классу) и её метрики:
     так видно качество на роликах, которых модель не видела;
  3. финальная модель на всех роликах -> ACTION_MODEL_PATH.
Статус пишется в MODELS_DIR/training_status.json, вывод скриптов в training.log.
"""

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from libs.config import settings

DATASET_CLASSES = {
    "0_normal": "Норма",
    "1_fight": "Драка",
    "2_bullying": "Буллинг",
    "3_theft": "Кража из кассы",
    "4_shoplifting": "Кража с витрины",
    "5_eating": "Поедание у витрины",
}
CLASS_KEYS = {"normal": "0_normal", "fight": "1_fight", "bullying": "2_bullying", "theft": "3_theft",
              "shoplifting": "4_shoplifting", "eating": "5_eating"}

STEP_TITLES = {
    "extract": "Извлечение поз из роликов",
    "evaluate_train": "Обучение оценочной модели",
    "evaluate": "Проверка на отложенных роликах",
    "train": "Обучение финальной модели",
}

_lock = threading.Lock()
_running = False


def status_path() -> Path:
    return Path(settings.MODELS_DIR) / "training_status.json"


def log_path() -> Path:
    return Path(settings.MODELS_DIR) / "training.log"


def eval_weights_path() -> Path:
    return Path(settings.MODELS_DIR) / "action_lstm_eval.pt"


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def read_status() -> dict:
    try:
        return json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "idle"}


def _write_status(**fields) -> dict:
    data = {**read_status(), **fields}
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return data


def read_log_tail(lines: int = 40) -> list[str]:
    try:
        text = log_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    # Прогресс-бары и \r не нужны в интерфейсе
    rows = [row.rsplit("\r", 1)[-1] for row in text.splitlines()]
    return [row for row in rows if row.strip()][-lines:]


def recover_stale_status() -> None:
    """После перезапуска worker незавершённое обучение помечается прерванным."""
    if read_status().get("state") == "running":
        _write_status(state="failed", finished_at=_now(), error="Обучение прервано перезапуском worker")


_METRIC_ROW = re.compile(r"^\s*(\w+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s*$")


def parse_metrics(output: str) -> dict | None:
    """Метрики по классам из первого отчёта evaluate_action_lstm.py (отложенные ролики)."""
    if "Held-out videos (not used for training)" not in output:
        return None
    section = output.split("Held-out videos (not used for training)", 1)[1]
    section = section.split("For comparison", 1)[0]
    accuracy = re.search(r"Accuracy:\s*([\d.]+)", section)
    classes = {}
    for line in section.splitlines():
        match = _METRIC_ROW.match(line)
        if match and match.group(1) in CLASS_KEYS:
            name, precision, recall, f1, avg_conf, support = match.groups()
            classes[CLASS_KEYS[name]] = {
                "precision": float(precision),
                "recall": float(recall),
                "f1": float(f1),
                "support": int(support),
            }
    return {"accuracy": float(accuracy.group(1)) if accuracy else None, "classes": classes}


def _window_counts() -> dict:
    """Сколько обучающих окон получилось по каждому классу после извлечения."""
    try:
        import numpy as np

        y = np.load(Path(settings.DATASET_DIR) / "y.npy")
    except Exception:
        return {}
    folders = list(DATASET_CLASSES)
    counts = {folder: 0 for folder in folders}
    for value in y.tolist():
        if 0 <= int(value) < len(folders):
            counts[folders[int(value)]] += 1
    return counts


def _count_videos() -> int:
    root = Path(settings.DATASET_DIR)
    return sum(1 for folder in DATASET_CLASSES for _ in (root / folder).glob("*.mp4"))


def _run(step: str, command: list[str], log) -> tuple[int, str]:
    """Запускает шаг и сразу пишет его вывод в журнал; для извлечения считает ролики."""
    total = _count_videos() if step == "extract" else None
    _write_status(step=step, step_title=STEP_TITLES[step], progress={"done": 0, "total": total} if total else None)
    log.write(f"\n=== {STEP_TITLES[step]}: {' '.join(command)}\n")
    log.flush()
    proc = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    lines = []
    done = 0
    last_update = time.monotonic()
    for line in proc.stdout:
        lines.append(line)
        log.write(line)
        log.flush()
        if total and line.startswith("Processing "):
            done += 1
            if time.monotonic() - last_update > 2:
                _write_status(progress={"done": done, "total": total})
                last_update = time.monotonic()
    code = proc.wait()
    if total:
        _write_status(progress={"done": done, "total": total})
    return code, "".join(lines)


def _pipeline(on_success) -> None:
    global _running
    try:
        with open(log_path(), "w", encoding="utf-8") as log:
            code, _ = _run("extract", ["python", "scripts/train_lstm.py", "--extract"], log)
            if code != 0:
                raise RuntimeError("Не удалось извлечь позы из роликов, подробности в журнале")
            windows = _window_counts()
            _write_status(windows=windows)

            metrics = None
            code, _ = _run(
                "evaluate_train",
                ["python", "scripts/train_lstm.py", "--train", "--holdout-frac", "0.2",
                 "--save-path", str(eval_weights_path())],
                log,
            )
            if code == 0:
                code, output = _run(
                    "evaluate",
                    ["python", "scripts/evaluate_action_lstm.py", "--weights", str(eval_weights_path())],
                    log,
                )
                metrics = parse_metrics(output) if code == 0 else None
            _write_status(metrics=metrics)

            code, _ = _run("train", ["python", "scripts/train_lstm.py", "--train"], log)
            if code != 0:
                raise RuntimeError("Финальная модель не обучилась, подробности в журнале")

        _write_status(state="completed", finished_at=_now(), step=None, step_title=None, error=None, progress=None)
        if on_success:
            on_success()
    except Exception as exc:  # статус должен отражать любую ошибку
        _write_status(state="failed", finished_at=_now(), error=str(exc))
    finally:
        with _lock:
            _running = False


def start_in_background(on_success=None) -> bool:
    """Запускает обучение, если оно ещё не идёт. Возвращает False, если уже идёт."""
    global _running
    with _lock:
        if _running:
            return False
        _running = True
    _write_status(state="running", started_at=_now(), finished_at=None, error=None,
                  step=None, step_title=None, metrics=None, windows=None, progress=None)
    threading.Thread(target=_pipeline, args=(on_success,), daemon=True, name="lstm-training").start()
    return True
