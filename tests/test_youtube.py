from libs import youtube
from libs.config import settings

BOT_CHECK = (
    "[youtube] SwNov0AgQKI: Downloading visionos player API JSON\n"
    "ERROR: [youtube] SwNov0AgQKI: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies "
    "for the authentication."
)


def test_command_passes_cookies_only_when_file_exists(tmp_path, monkeypatch):
    cookies = tmp_path / "youtube_cookies.txt"
    monkeypatch.setattr(settings, "YOUTUBE_COOKIES_FILE", str(cookies))

    assert youtube.cookies_file() is None
    assert "--cookies" not in youtube.build_command("https://youtu.be/x", "out.%(ext)s", youtube.cookies_file())

    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    command = youtube.build_command("https://youtu.be/x", "out.%(ext)s", youtube.cookies_file())
    assert command[command.index("--cookies") + 1] == str(cookies)
    assert command[-1] == "https://youtu.be/x"


def test_format_prefers_h264_over_av1():
    # OpenCV в worker не декодирует AV1: сначала просим H.264, AV1 только в последнюю очередь.
    first, *rest = youtube.VIDEO_FORMAT.split("/")
    assert "[vcodec^=avc1]" in first
    assert "[vcodec!^=av01]" in rest[0]
    command = youtube.build_command("https://youtu.be/x", "out.%(ext)s")
    assert command[command.index("-f") + 1] == youtube.VIDEO_FORMAT


def test_empty_cookies_file_is_ignored(tmp_path, monkeypatch):
    cookies = tmp_path / "youtube_cookies.txt"
    cookies.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings, "YOUTUBE_COOKIES_FILE", str(cookies))

    assert youtube.cookies_file() is None


def test_bot_check_error_is_explained_in_russian():
    message = youtube.explain_error(BOT_CHECK, cookies_used=False)

    assert message.startswith("YouTube просит подтвердить, что запрос делает не робот")
    assert "Загрузите видео файлом" in message
    assert "Подробности yt-dlp: ERROR: [youtube] SwNov0AgQKI: Sign in" in message


def test_bot_check_with_cookies_points_to_stale_cookies():
    assert youtube.explain_error(BOT_CHECK, cookies_used=True).startswith("YouTube не принял cookies")


def test_other_errors_are_explained():
    assert youtube.explain_error("ERROR: [youtube] x: Video unavailable", False).startswith("Видео недоступно")
    assert youtube.explain_error("ERROR: [youtube] x: Private video. Sign in", False).startswith("Это приватное видео")
    assert youtube.explain_error("[download] x does not pass filter (duration <= 3600), skipping ..", False).startswith("Видео длиннее")
    assert youtube.explain_error("", False) == "Не удалось скачать видео с YouTube."


def test_system_endpoint_reports_cookies(client, tmp_path, monkeypatch):
    cookies = tmp_path / "youtube_cookies.txt"
    monkeypatch.setattr(settings, "YOUTUBE_COOKIES_FILE", str(cookies))
    assert client.get("/api/detection-tests/system").json()["youtube_cookies"] is False

    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    assert client.get("/api/detection-tests/system").json()["youtube_cookies"] is True
