import os
import signal
import subprocess
import threading
import time


running = True


def _stop(_signum, _frame):
    global running
    running = False


def _source_urls():
    raw = os.getenv("TEST_SOURCE_URLS", "")
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]


def _resolve_source(source_url: str) -> str:
    if "youtube.com/" not in source_url and "youtu.be/" not in source_url:
        return source_url

    # Resolve a direct video-only URL. The worker AI only needs video frames.
    cmd = [
        "yt-dlp",
        "-g",
        "-f",
        "bv*[height<=720]/best[height<=720]/best",
        source_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "yt-dlp failed")

    urls = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not urls:
        raise RuntimeError("yt-dlp returned no media URL")
    return urls[0]


def _ffmpeg_input(index: int):
    sources = _source_urls()
    if not sources:
        size = os.getenv("TEST_VIDEO_SIZE", "640x360")
        fps = int(os.getenv("TEST_VIDEO_FPS", "10"))
        return ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}"]

    source = sources[(index - 1) % len(sources)]
    resolved = _resolve_source(source)
    if os.path.exists(resolved):
        return ["-stream_loop", "-1", "-i", resolved]
    return ["-i", resolved]


def _publish_loop(index: int):
    host = os.getenv("TEST_RTSP_HOST", "rtsp")
    port = int(os.getenv("TEST_RTSP_PORT", "8554"))
    fps = int(os.getenv("TEST_VIDEO_FPS", "10"))
    scale = os.getenv("TEST_SOURCE_SCALE", "640:-2")
    url = f"rtsp://{host}:{port}/cam{index}"

    while running:
        try:
            input_args = _ffmpeg_input(index)
        except Exception as exc:
            print(f"[rtsp-publisher] failed to resolve source for cam{index}: {exc}", flush=True)
            time.sleep(10)
            continue

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-re",
            *input_args,
            "-an",
            "-vf",
            f"scale={scale},fps={fps}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-g",
            str(max(fps * 2, 2)),
            "-sc_threshold",
            "0",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            url,
        ]

        print(f"[rtsp-publisher] starting cam{index}: {url}", flush=True)
        proc = subprocess.Popen(cmd)
        while running and proc.poll() is None:
            time.sleep(1)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if running:
            print(f"[rtsp-publisher] cam{index} exited, restarting in 1s", flush=True)
            time.sleep(1)


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    count = int(os.getenv("TEST_CAMERA_COUNT", "15"))
    time.sleep(float(os.getenv("TEST_RTSP_START_DELAY", "2")))

    threads = []
    for index in range(1, count + 1):
        thread = threading.Thread(target=_publish_loop, args=(index,), daemon=True)
        thread.start()
        threads.append(thread)

    while running:
        time.sleep(1)

    for thread in threads:
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
