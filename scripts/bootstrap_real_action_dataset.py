import argparse
import json
import os
import shutil
import subprocess
import urllib.parse
from pathlib import Path

import requests


DATASET_DIR = Path("data/dataset")
RAW_DIR = DATASET_DIR / "_internet_raw"

GITHUB_API = "https://api.github.com/repos"


def _get_json(url: str):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def _download(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)


def _github_raw_url(owner_repo: str, ref: str, path: str) -> str:
    quoted = urllib.parse.quote(path)
    return f"https://raw.githubusercontent.com/{owner_repo}/{ref}/{quoted}"


def _run_ffmpeg(src: Path, dest: Path, loop_gif: bool):
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y"]
    if loop_gif:
        cmd.extend(["-stream_loop", "5"])
    cmd.extend(
        [
            "-i",
            str(src),
            "-t",
            "10",
            "-vf",
            "fps=10,scale=640:-2",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            str(dest),
        ]
    )
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _clear_bootstrap_files():
    for class_dir in ["0_normal", "3_theft", "4_shoplifting"]:
        folder = DATASET_DIR / class_dir
        if not folder.exists():
            continue
        for path in folder.glob("internet_*"):
            if path.is_file():
                path.unlink()
    shutil.rmtree(RAW_DIR, ignore_errors=True)
    manifest = DATASET_DIR / "internet_sources_manifest.json"
    if manifest.exists():
        manifest.unlink()


def _select_github_contents(owner_repo: str, ref: str, path: str, suffix: str, count: int, max_size_mb: int):
    url = f"{GITHUB_API}/{owner_repo}/contents/{urllib.parse.quote(path)}?ref={ref}"
    items = _get_json(url)
    selected = []
    for item in items:
        if item.get("type") != "file":
            continue
        if not item["name"].lower().endswith(suffix):
            continue
        if item.get("size", 0) > max_size_mb * 1024 * 1024:
            continue
        selected.append(item)
    selected.sort(key=lambda item: (item.get("size", 0), item["name"]))
    return selected[:count]


def _stage_files(entries, class_dir: str, source_name: str, convert_gif: bool):
    output_dir = DATASET_DIR / class_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    staged = []

    for idx, item in enumerate(entries, start=1):
        suffix = Path(item["name"]).suffix.lower()
        raw_path = RAW_DIR / source_name / item["name"]
        download_url = item.get("download_url")
        if not download_url:
            download_url = _github_raw_url(item["owner_repo"], item["ref"], item["path"])

        print(f"[dataset] downloading {download_url}")
        _download(download_url, raw_path)

        out_path = output_dir / f"internet_{source_name}_{idx:02d}.mp4"
        _run_ffmpeg(raw_path, out_path, loop_gif=convert_gif or suffix == ".gif")
        staged.append(
            {
                "class_dir": class_dir,
                "output": str(out_path),
                "source": download_url,
                "source_repo": item.get("owner_repo"),
                "source_path": item.get("path"),
            }
        )

    return staged


def bootstrap(normal_count: int, theft_count: int, shoplifting_count: int, clear: bool):
    if clear:
        _clear_bootstrap_files()

    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []

    robbery_repo = "ZakiaYahya/Youtube-Robbery-Video-Dataset"
    normal = _select_github_contents(
        robbery_repo,
        "master",
        "Dataset/Train-Set/norobbery",
        ".mp4",
        normal_count,
        max_size_mb=8,
    )
    theft = _select_github_contents(
        robbery_repo,
        "master",
        "Dataset/Train-Set/robbery",
        ".mp4",
        theft_count,
        max_size_mb=8,
    )
    for item in normal + theft:
        item["owner_repo"] = robbery_repo
        item["ref"] = "master"

    shoplifting_repo = "1amitos1/Shoplifting-Detection"
    shoplifting = _select_github_contents(
        shoplifting_repo,
        "main",
        "DB_Sample/output",
        ".gif",
        shoplifting_count,
        max_size_mb=2,
    )
    for item in shoplifting:
        item["owner_repo"] = shoplifting_repo
        item["ref"] = "main"

    manifest.extend(_stage_files(normal, "0_normal", "normal", convert_gif=False))
    manifest.extend(_stage_files(theft, "3_theft", "theft", convert_gif=False))
    manifest.extend(_stage_files(shoplifting, "4_shoplifting", "shoplifting", convert_gif=True))

    manifest_path = DATASET_DIR / "internet_sources_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[dataset] staged {len(manifest)} videos")
    print(f"[dataset] manifest: {manifest_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download a small internet real-sample action dataset.")
    parser.add_argument("--normal-count", type=int, default=6)
    parser.add_argument("--theft-count", type=int, default=6)
    parser.add_argument("--shoplifting-count", type=int, default=8)
    parser.add_argument("--clear", action="store_true", help="Remove prior internet_* files before downloading")
    args = parser.parse_args()

    bootstrap(
        normal_count=args.normal_count,
        theft_count=args.theft_count,
        shoplifting_count=args.shoplifting_count,
        clear=args.clear,
    )
