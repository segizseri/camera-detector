import urllib.parse

from libs.camera_streams import strip_rtsp_credentials
from libs.crypto import encrypt_password
from libs.models import Camera


def migrate_rtsp_credentials(db) -> int:
    updated = 0
    cameras = db.query(Camera).all()
    for camera in cameras:
        if not camera.rtsp_url:
            continue

        parsed = urllib.parse.urlsplit(camera.rtsp_url)
        if not parsed.username and not parsed.password:
            continue

        if parsed.username and not camera.username:
            camera.username = urllib.parse.unquote(parsed.username)

        if parsed.password and not camera.encrypted_password:
            camera.encrypted_password = encrypt_password(urllib.parse.unquote(parsed.password))

        stripped = strip_rtsp_credentials(camera.rtsp_url)
        if stripped != camera.rtsp_url:
            camera.rtsp_url = stripped
            updated += 1

    if updated:
        db.commit()
    return updated
