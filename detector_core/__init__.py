"""AI-движок детекций camera-detector.

Пакет не зависит от веб-приложения: здесь нельзя импортировать ``libs``,
``apps``, ``fastapi``, ``sqlalchemy``; тяжёлые рантаймы (``torch``,
``ultralytics``) подключаются только в реализациях компонентов, но не в
``detector_core.contract``. Описание контракта: ``docs/detector_engine.md``.
"""
