// Сгенерировано scripts/export_ui_catalog.py из detector_core/contract/catalog.py.
// Не редактируйте вручную: tests/test_ui_pages.py сверяет файл с каталогом.
window.DETECTOR_CATALOG = {
  "contract_version": "0.1",
  "detectors": [
    {
      "id": "fight",
      "title": "Драка",
      "description": "Обоюдная физическая агрессия двух и более людей: удары, толчки, борьба.",
      "maturity": "prototype",
      "event_type": "fight",
      "legacy_event_type": "fight_suspected",
      "legacy_flag": "detect_fights",
      "legacy_batch_key": "fight",
      "min_fps": 5.0,
      "recommended_fps": 5.0,
      "zones": [],
      "external_events": [],
      "components": [
        "pose",
        "tracker",
        "interaction_model"
      ]
    },
    {
      "id": "bullying",
      "title": "Буллинг",
      "description": "Длительная односторонняя агрессия против одного человека: та же модель взаимодействия, что у драки, плюс правила длительности и окружения.",
      "maturity": "prototype",
      "event_type": "bullying",
      "legacy_event_type": "bullying_suspected",
      "legacy_flag": "detect_bullying",
      "legacy_batch_key": "bullying",
      "min_fps": 5.0,
      "recommended_fps": 5.0,
      "zones": [],
      "external_events": [],
      "components": [
        "pose",
        "tracker",
        "interaction_model"
      ]
    },
    {
      "id": "cash_theft",
      "title": "Кража из кассы",
      "description": "Доступ к денежному ящику без подтверждающего POS-события: рука в зоне ящика вне транзакции, no_sale, открытие ящика при оплате картой.",
      "maturity": "concept",
      "event_type": "cash_theft",
      "legacy_event_type": "theft_suspected",
      "legacy_flag": "detect_theft",
      "legacy_batch_key": "theft",
      "min_fps": 5.0,
      "recommended_fps": 5.0,
      "zones": [
        {
          "kind": "cash_drawer",
          "title": "Зона кассы",
          "description": "Полигон денежного ящика (бывшая theft_zone).",
          "legacy_column": "theft_zone"
        }
      ],
      "external_events": [
        {
          "kind": "pos",
          "description": "Поток событий кассы, привязанной к камере."
        }
      ],
      "components": [
        "pose",
        "tracker",
        "pos_ingest"
      ]
    },
    {
      "id": "shelf_theft",
      "title": "Кража с витрины",
      "description": "Человек берёт товар в зоне витрины и прячет его в карман, сумку или под одежду.",
      "maturity": "concept",
      "event_type": "shelf_theft",
      "legacy_event_type": "shoplifting_suspected",
      "legacy_flag": "detect_shoplifting",
      "legacy_batch_key": "shoplifting",
      "min_fps": 5.0,
      "recommended_fps": 5.0,
      "zones": [
        {
          "kind": "display",
          "title": "Зона витрины",
          "description": "Полигон витрины (бывшая display_zone).",
          "legacy_column": "display_zone"
        }
      ],
      "external_events": [],
      "components": [
        "pose",
        "tracker",
        "object_detector"
      ]
    },
    {
      "id": "eating",
      "title": "Поедание у витрины",
      "description": "Человек ест или пьёт товар у витрины: предмет из зоны витрины многократно у рта.",
      "maturity": "concept",
      "event_type": "eating",
      "legacy_event_type": "eating_suspected",
      "legacy_flag": "detect_eating",
      "legacy_batch_key": "eating",
      "min_fps": 5.0,
      "recommended_fps": 5.0,
      "zones": [
        {
          "kind": "display",
          "title": "Зона витрины",
          "description": "Полигон витрины (бывшая display_zone).",
          "legacy_column": "display_zone"
        }
      ],
      "external_events": [],
      "components": [
        "pose",
        "tracker",
        "object_detector"
      ]
    }
  ]
};
