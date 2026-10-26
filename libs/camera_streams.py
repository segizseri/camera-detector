import urllib.parse

from libs.crypto import decrypt_password


def nvr_stream_path(channel: int, brand_preset: str = "hikvision", stream_profile: str = "substream") -> str:
    if brand_preset == "hikvision":
        suffix = "02" if stream_profile == "substream" else "01"
        return f"/Streaming/Channels/{channel}{suffix}"

    subtype = "1" if stream_profile == "substream" else "0"
    return f"/cam/realmonitor?channel={channel}&subtype={subtype}"


def public_rtsp_url(host: str, port: int, path: str) -> str:
    return f"rtsp://{host}:{port}{path}"


def _netloc_without_userinfo(parsed: urllib.parse.SplitResult) -> str:
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{parsed.port}" if parsed.port else host


def strip_rtsp_credentials(rtsp_url: str) -> str:
    if not rtsp_url:
        return rtsp_url

    parsed = urllib.parse.urlsplit(rtsp_url)
    if not parsed.username and not parsed.password:
        return rtsp_url

    return urllib.parse.urlunsplit(
        (parsed.scheme, _netloc_without_userinfo(parsed), parsed.path, parsed.query, parsed.fragment)
    )


def inject_rtsp_credentials(rtsp_url: str, username: str, password: str) -> str:
    if not rtsp_url or not username or not password:
        return rtsp_url

    parsed = urllib.parse.urlsplit(strip_rtsp_credentials(rtsp_url))
    userinfo = f"{urllib.parse.quote(username)}:{urllib.parse.quote(password)}"
    netloc = f"{userinfo}@{_netloc_without_userinfo(parsed)}"
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def camera_rtsp_url(camera) -> str:
    """Return a runtime RTSP URL. New rows store rtsp_url without credentials."""
    rtsp_url = camera.rtsp_url or ""
    password = decrypt_password(camera.encrypted_password or "")
    if password and camera.username:
        return inject_rtsp_credentials(rtsp_url, camera.username, password)
    return rtsp_url


def masked_rtsp_url(rtsp_url: str) -> str:
    if not rtsp_url:
        return rtsp_url

    parsed = urllib.parse.urlsplit(rtsp_url)
    if not parsed.username and not parsed.password:
        return rtsp_url

    username = urllib.parse.unquote(parsed.username or "")
    userinfo = f"{urllib.parse.quote(username)}:***" if username else "***"
    netloc = f"{userinfo}@{_netloc_without_userinfo(parsed)}"
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def public_camera(camera) -> dict:
    rtsp_url = strip_rtsp_credentials(camera.rtsp_url or "")
    return {
        "id": camera.id,
        "bus_id": camera.bus_id,
        "name": camera.name,
        "nvr_ip": camera.nvr_ip,
        "rtsp_url": masked_rtsp_url(rtsp_url),
        "username": camera.username,
        "channel": camera.channel,
        "enabled": camera.enabled,
        "ai_enabled": camera.ai_enabled,
        "fps_limit": camera.fps_limit,
        "theft_zone": camera.theft_zone,
        "counting_config": camera.counting_config,
        "detect_fights": camera.detect_fights,
        "detect_bullying": camera.detect_bullying,
        "detect_theft": camera.detect_theft,
        "detect_passengers": camera.detect_passengers,
        "detect_shoplifting": camera.detect_shoplifting,
        "detect_eating": camera.detect_eating,
        "display_zone": camera.display_zone,
        "status": camera.status,
        "last_seen": camera.last_seen,
    }
