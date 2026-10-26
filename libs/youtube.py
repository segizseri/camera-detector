"""Скачивание YouTube-видео для проверки детекций через yt-dlp.

YouTube может требовать вход («Sign in to confirm you’re not a bot»), особенно
для серверов. Тогда нужен cookies.txt аккаунта: если файл YOUTUBE_COOKIES_FILE
существует, он передаётся yt-dlp через --cookies. Иначе пользователь получает
понятное сообщение и может загрузить видео файлом.
"""

from pathlib import Path

from libs.config import settings

# Сначала H.264: OpenCV в worker не декодирует AV1, который YouTube часто отдаёт как «лучший».
VIDEO_FORMAT = (
    "bv*[height<=720][vcodec^=avc1]"
    "/bv*[height<=720][vcodec!^=av01]"
    "/b[height<=720][vcodec!^=av01]"
    "/bv*[height<=720]/b[height<=720]/b"
)


def cookies_file() -> Path | None:
    path = Path(settings.YOUTUBE_COOKIES_FILE)
    try:
        return path if path.is_file() and path.stat().st_size > 0 else None
    except OSError:
        return None


def build_command(url: str, output_template: str, cookies: Path | None = None) -> list[str]:
    command = [
        "yt-dlp",
        "--no-playlist",
        "--no-progress",
        "--max-filesize",
        f"{settings.DETECTION_TEST_MAX_UPLOAD_MB}M",
        "--match-filter",
        f"duration <= {settings.DETECTION_TEST_MAX_DURATION_SECONDS}",
        "-f",
        VIDEO_FORMAT,
        "-o",
        output_template,
    ]
    if cookies is not None:
        command += ["--cookies", str(cookies)]
    command.append(url)
    return command


def explain_error(output: str, cookies_used: bool) -> str:
    """Понятное сообщение по выводу yt-dlp; последняя строка вывода идёт как подробности."""
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    detail = lines[-1] if lines else ""
    text = (output or "").lower()

    if "not a bot" in text:
        if cookies_used:
            message = (
                "YouTube не принял cookies: они устарели или в браузере не был выполнен вход. "
                "Экспортируйте cookies заново или загрузите видео файлом."
            )
        else:
            message = (
                "YouTube просит подтвердить, что запрос делает не робот, и не отдаёт видео этому серверу без входа. "
                "Загрузите видео файлом во вкладке «Файл» или подключите cookies YouTube (README, «Проверка детекций на видео»)."
            )
    elif "confirm your age" in text or "age-restricted" in text:
        message = "Видео с ограничением по возрасту: YouTube отдаёт его только после входа. Подключите cookies YouTube или загрузите видео файлом."
    elif "private video" in text:
        message = "Это приватное видео: скачать его можно только из аккаунта с доступом. Загрузите видео файлом."
    elif "video unavailable" in text or "not available" in text:
        message = "Видео недоступно: оно удалено, скрыто или закрыто для этого региона."
    elif "does not pass filter" in text:
        minutes = settings.DETECTION_TEST_MAX_DURATION_SECONDS // 60
        message = f"Видео длиннее разрешённых {minutes} мин. Возьмите более короткий ролик или фрагмент."
    elif "max-filesize" in text or "larger than max" in text:
        message = f"Видео больше разрешённых {settings.DETECTION_TEST_MAX_UPLOAD_MB} МБ."
    else:
        message = "Не удалось скачать видео с YouTube."

    return f"{message}\nПодробности yt-dlp: {detail}" if detail else message
