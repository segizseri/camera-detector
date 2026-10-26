import json
import math
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import cv2

from libs import youtube
from libs.config import settings
from libs.database import Base, SessionLocal, engine
from libs.models import DetectionTestJob
from libs.rules import AIActionDetector, PassengerCounter


ACTION_META = {
    1: {"key": "fight", "event_type": "fight_suspected", "label": "Драка"},
    2: {"key": "bullying", "event_type": "bullying_suspected", "label": "Буллинг"},
    3: {"key": "theft", "event_type": "theft_suspected", "label": "Кража"},
    4: {"key": "shoplifting", "event_type": "shoplifting_suspected", "label": "Кража из витрины"},
    5: {"key": "eating", "event_type": "eating_suspected", "label": "Поедание у витрины"},
}
YOUTUBE_HOSTS = {"youtube.com", "youtu.be", "youtube-nocookie.com"}
PASSENGER_LINE = [[0.05, 0.5], [0.95, 0.5]]


class DetectionTestRunner:
    def __init__(self, poll_interval: float = 2.0):
        self.poll_interval = poll_interval
        self.running = True

    def stop(self):
        self.running = False

    def loop(self):
        while self.running:
            try:
                Base.metadata.create_all(bind=engine)
                break
            except Exception as exc:
                print(f"Detection test database unavailable: {exc}", flush=True)
                time.sleep(self.poll_interval)
        if not self.running:
            return
        self._recover_interrupted_jobs()
        print("Detection test runner started.", flush=True)
        while self.running:
            job_id = self._claim_next_job()
            if not job_id:
                time.sleep(self.poll_interval)
                continue
            try:
                self._process(job_id)
            except Exception as exc:
                print(f"[detection-test:{job_id}] failed: {exc}", flush=True)
                self._fail(job_id, str(exc))

    def _recover_interrupted_jobs(self):
        db = SessionLocal()
        try:
            jobs = db.query(DetectionTestJob).filter(DetectionTestJob.status == "processing").all()
            for job in jobs:
                job.status = "queued"
                job.stage = "queued"
                job.progress = 0.0
                job.error = None
                job.started_at = None
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"Detection test recovery skipped: {exc}", flush=True)
        finally:
            db.close()

    def _claim_next_job(self) -> str | None:
        db = SessionLocal()
        try:
            job = (
                db.query(DetectionTestJob)
                .filter(DetectionTestJob.status == "queued")
                .order_by(DetectionTestJob.created_at.asc())
                .first()
            )
            if not job:
                return None
            job.status = "processing"
            job.stage = "preparing"
            job.progress = 1.0
            job.started_at = datetime.utcnow()
            job.error = None
            db.commit()
            return job.id
        except Exception as exc:
            db.rollback()
            print(f"Detection test queue unavailable: {exc}", flush=True)
            return None
        finally:
            db.close()

    def _get_job(self, job_id: str) -> DetectionTestJob:
        db = SessionLocal()
        try:
            job = db.query(DetectionTestJob).filter(DetectionTestJob.id == job_id).first()
            if not job:
                raise RuntimeError("Задание анализа удалено")
            db.expunge(job)
            return job
        finally:
            db.close()

    def _update(self, job_id: str, **values):
        db = SessionLocal()
        try:
            job = db.query(DetectionTestJob).filter(DetectionTestJob.id == job_id).first()
            if not job:
                return
            for key, value in values.items():
                setattr(job, key, value)
            job.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()

    def _fail(self, job_id: str, message: str):
        self._update(
            job_id,
            status="failed",
            stage="failed",
            error=message[:4000],
            finished_at=datetime.utcnow(),
        )

    def _process(self, job_id: str):
        job = self._get_job(job_id)
        detectors = json.loads(job.detectors_json)
        job_dir = Path(settings.DETECTION_TESTS_DIR) / job.id
        job_dir.mkdir(parents=True, exist_ok=True)

        action_model_paths = {
            "general": Path(settings.ACTION_MODEL_PATH),
            "eating": Path(settings.MODELS_DIR) / "action_lstm_eating.pt",
        }
        action_model_path = action_model_paths.get(job.model_key)
        if not action_model_path:
            raise RuntimeError("Неизвестная AI-модель в задании")
        if not action_model_path.is_file():
            raise RuntimeError(f"AI-модель {action_model_path.name} не найдена")

        input_path = Path(job.input_path) if job.input_path else None
        if job.source_type == "youtube":
            self._update(job.id, stage="downloading", progress=3.0)
            input_path = self._download_youtube(job.source_url or "", job_dir)
            self._update(job.id, input_path=str(input_path), stage="opening", progress=10.0)
        elif not input_path or not input_path.is_file():
            raise RuntimeError("Загруженное видео не найдено")
        input_path = self._ensure_decodable(input_path)

        cap = cv2.VideoCapture(str(input_path))
        if not cap.isOpened():
            raise RuntimeError("Не удалось открыть видео. Проверьте формат или кодек")

        source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if not math.isfinite(source_fps) or source_fps <= 0:
            source_fps = 25.0
        source_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = source_frames / source_fps if source_frames > 0 else None
        if duration and duration > settings.DETECTION_TEST_MAX_DURATION_SECONDS:
            cap.release()
            raise RuntimeError(
                f"Видео длиннее лимита {settings.DETECTION_TEST_MAX_DURATION_SECONDS // 60} минут"
            )

        sample_fps = max(1.0, min(float(job.sample_fps or 5.0), 10.0))
        frame_step = max(1, int(round(source_fps / sample_fps)))
        output_fps = source_fps / frame_step
        estimated_samples = math.ceil(source_frames / frame_step) if source_frames else None
        self._update(
            job.id,
            stage="loading_models",
            progress=12.0,
            duration_seconds=duration,
            total_frames=estimated_samples,
        )

        from libs.ai_models import PersonPoseTracker, load_pose_model

        # Same pose model, input size and tracker as live cameras and dataset extraction.
        pose_tracker = PersonPoseTracker(load_pose_model())
        action_detector = AIActionDetector(
            f"detection-test-{job.id}",
            weights_path=str(action_model_path),
        )
        passenger_counter = PassengerCounter(f"detection-test-{job.id}")
        passenger_config = json.dumps([{"label": "Центральная линия", "line": PASSENGER_LINE}])

        events_dir = job_dir / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        temp_video = job_dir / "annotated.raw.mp4"
        output_video = job_dir / "annotated.mp4"
        writer = None
        events = []
        action_frame_counts = {str(class_id): 0 for class_id in ACTION_META}
        last_events = {class_id: -float("inf") for class_id in ACTION_META}
        max_people = 0
        person_frames = 0
        sampled_frames = 0
        source_index = 0

        self._update(job.id, stage="analyzing", progress=15.0)

        try:
            while self.running:
                ok, frame = cap.read()
                if not ok:
                    break
                current_index = source_index
                source_index += 1
                if current_index % frame_step != 0:
                    continue

                timestamp_seconds = current_index / source_fps
                result = pose_tracker.track(frame)
                xyxy = result.boxes.xyxy.cpu().numpy().tolist()
                confidences = result.boxes.conf.cpu().numpy().tolist()
                classes = result.boxes.cls.cpu().numpy().tolist()
                bboxes = [box + [confidences[i], classes[i]] for i, box in enumerate(xyxy)]
                ids = result.boxes.id.cpu().numpy().tolist() if result.boxes.id is not None else []
                keypoints = None
                if getattr(result, "keypoints", None) is not None:
                    keypoints = result.keypoints.data.cpu().numpy()

                people = sum(1 for class_id in classes if int(class_id) == 0)
                max_people = max(max_people, people)
                if people:
                    person_frames += 1

                action_class, action_prob, track_id = action_detector.add_frame(
                    bboxes,
                    keypoints,
                    ids,
                    timestamp_seconds,
                )
                action_meta = ACTION_META.get(action_class)
                is_selected_action = bool(action_meta and action_meta["key"] in detectors)
                is_active_action = bool(
                    is_selected_action
                    and action_prob >= action_detector.thresholds.get(action_class, 0.6)
                )
                if is_active_action:
                    action_frame_counts[str(action_class)] += 1

                if "passengers" in detectors and ids:
                    height, width = frame.shape[:2]
                    normalized_boxes = [
                        [box[0] / width, box[1] / height, box[2] / width, box[3] / height]
                        for box in bboxes
                    ]
                    passenger_counter.update(normalized_boxes, ids, passenger_config)

                annotated = result.plot()
                if "passengers" in detectors:
                    height, width = annotated.shape[:2]
                    start = (int(PASSENGER_LINE[0][0] * width), int(PASSENGER_LINE[0][1] * height))
                    end = (int(PASSENGER_LINE[1][0] * width), int(PASSENGER_LINE[1][1] * height))
                    cv2.line(annotated, start, end, (255, 180, 0), 3)

                if is_active_action:
                    overlay = f"DETECTED: {action_meta['key'].upper()} {action_prob:.0%}"
                    cv2.rectangle(annotated, (16, 14), (min(annotated.shape[1] - 16, 620), 62), (0, 0, 0), -1)
                    cv2.putText(
                        annotated,
                        overlay,
                        (26, 49),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.9,
                        (0, 60, 255),
                        2,
                        cv2.LINE_AA,
                    )

                    cooldown = action_detector.cooldowns.get(action_class, 30)
                    if timestamp_seconds - last_events[action_class] >= cooldown:
                        last_events[action_class] = timestamp_seconds
                        event_number = len(events) + 1
                        snapshot_path = events_dir / f"event-{event_number:03d}.jpg"
                        cv2.imwrite(str(snapshot_path), annotated)
                        events.append(
                            {
                                "id": event_number,
                                "class_id": action_class,
                                "detector": action_meta["key"],
                                "event_type": action_meta["event_type"],
                                "label": action_meta["label"],
                                "timestamp_seconds": round(timestamp_seconds, 2),
                                "confidence": round(float(action_prob), 4),
                                "track_id": int(track_id) if track_id is not None else None,
                                "snapshot_path": str(snapshot_path),
                            }
                        )

                annotated = self._resize_for_preview(annotated)
                if writer is None:
                    height, width = annotated.shape[:2]
                    writer = cv2.VideoWriter(
                        str(temp_video),
                        cv2.VideoWriter_fourcc(*"mp4v"),
                        output_fps,
                        (width, height),
                    )
                    if not writer.isOpened():
                        raise RuntimeError("Не удалось создать видео с результатом")
                writer.write(annotated)
                sampled_frames += 1

                if sampled_frames % 10 == 0:
                    if source_frames:
                        progress = 15.0 + min(current_index / source_frames, 1.0) * 75.0
                    else:
                        progress = min(88.0, 15.0 + sampled_frames / 20.0)
                    self._update(
                        job.id,
                        progress=progress,
                        processed_frames=sampled_frames,
                        results_json=json.dumps(
                            self._results_payload(
                                events,
                                max_people,
                                person_frames,
                                passenger_counter,
                                action_frame_counts,
                            ),
                            ensure_ascii=False,
                        ),
                    )
        finally:
            cap.release()
            if writer is not None:
                writer.release()

        if not self.running:
            raise RuntimeError("AI worker остановлен во время анализа")
        if sampled_frames == 0 or not temp_video.is_file():
            raise RuntimeError("В видео не найдено кадров для анализа")

        self._update(job.id, stage="encoding", progress=92.0, processed_frames=sampled_frames)
        self._encode_preview(temp_video, output_video)

        results_payload = self._results_payload(
            events,
            max_people,
            person_frames,
            passenger_counter,
            action_frame_counts,
        )
        self._update(
            job.id,
            status="completed",
            stage="completed",
            progress=100.0,
            output_video_path=str(output_video),
            duration_seconds=duration,
            processed_frames=sampled_frames,
            total_frames=sampled_frames,
            results_json=json.dumps(results_payload, ensure_ascii=False),
            finished_at=datetime.utcnow(),
        )
        print(f"[detection-test:{job.id}] completed with {len(events)} events", flush=True)

    @staticmethod
    def _resize_for_preview(frame):
        height, width = frame.shape[:2]
        scale = min(1.0, 960.0 / max(width, 1))
        target_width = max(2, int(width * scale) // 2 * 2)
        target_height = max(2, int(height * scale) // 2 * 2)
        if (target_width, target_height) == (width, height):
            return frame
        return cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _results_payload(events, max_people, person_frames, passenger_counter, action_frame_counts):
        counts = passenger_counter.counts.get("Центральная линия", {"in": 0, "out": 0})
        return {
            "events": events,
            "event_count": len(events),
            "max_people": max_people,
            "frames_with_people": person_frames,
            "passenger_counts": {"in": counts.get("in", 0), "out": counts.get("out", 0)},
            "action_frame_counts": action_frame_counts,
        }

    @staticmethod
    def _is_youtube_url(value: str) -> bool:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        return parsed.scheme in {"http", "https"} and any(
            host == item or host.endswith(f".{item}") for item in YOUTUBE_HOSTS
        )

    def _download_youtube(self, url: str, job_dir: Path) -> Path:
        if not self._is_youtube_url(url):
            raise RuntimeError("Разрешены только YouTube-ссылки")
        output_template = str(job_dir / "source.%(ext)s")
        cookies = youtube.cookies_file()
        command = youtube.build_command(url, output_template, cookies)
        result = subprocess.run(command, capture_output=True, text=True, timeout=900)
        output = f"{result.stdout or ''}\n{result.stderr or ''}"
        if result.returncode != 0:
            raise RuntimeError(youtube.explain_error(output, cookies is not None))
        candidates = [path for path in job_dir.glob("source.*") if path.is_file()]
        if not candidates:
            # yt-dlp завершается без ошибки, если ролик не прошёл фильтр длительности или размера.
            raise RuntimeError(youtube.explain_error(output, cookies is not None))
        return max(candidates, key=lambda path: path.stat().st_size)

    @staticmethod
    def _ensure_decodable(path: Path) -> Path:
        """Видео, первый кадр которого OpenCV не читает (например, AV1), перекодируется в H.264."""
        cap = cv2.VideoCapture(str(path))
        readable = cap.isOpened() and cap.read()[0]
        cap.release()
        if readable:
            return path

        target = path.with_name("source_h264.mp4")
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0 or not target.is_file():
            raise RuntimeError("Не удалось прочитать видео: кодек не поддерживается, а перекодирование в H.264 не удалось")
        return target

    @staticmethod
    def _encode_preview(source: Path, target: Path):
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(target),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffmpeg не смог подготовить видео результата")
        source.unlink(missing_ok=True)
