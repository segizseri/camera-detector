"""Экспорт JSON Schema контракта и эталонного каталога.

    python -m detector_core.contract.schema_export [docs/schemas]
"""

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from detector_core.contract.catalog import builtin_catalog
from detector_core.contract.ids import CONTRACT_VERSION
from detector_core.contract.models import (
    CameraConfig,
    ConfigIssue,
    Detection,
    DetectorCatalog,
    DetectorConfig,
    DetectorInfo,
    Event,
    ExternalEvent,
    Zone,
)

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "detector_info": DetectorInfo,
    "detector_catalog": DetectorCatalog,
    "camera_config": CameraConfig,
    "detector_config": DetectorConfig,
    "zone": Zone,
    "detection": Detection,
    "event": Event,
    "external_event": ExternalEvent,
    "config_issue": ConfigIssue,
}

DEFAULT_OUT_DIR = Path("docs/schemas")


def build_documents() -> dict[str, dict]:
    """Имя файла -> содержимое. Схемы входов строятся в режиме validation, выходов — serialization."""
    documents: dict[str, dict] = {}
    for name, model in SCHEMA_MODELS.items():
        mode = "validation" if name in {"camera_config", "detector_config", "zone", "external_event"} else "serialization"
        schema = model.model_json_schema(mode=mode)
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://camera-detector.local/schemas/{CONTRACT_VERSION}/{name}.schema.json",
            **schema,
        }
        documents[f"{name}.schema.json"] = schema
    documents["catalog.json"] = builtin_catalog().model_dump(mode="json")
    return documents


def render(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def write_schemas(out_dir: Path = DEFAULT_OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, document in build_documents().items():
        path = out_dir / filename
        path.write_text(render(document), encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT_DIR
    for path in write_schemas(target):
        print(path)
