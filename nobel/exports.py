"""Экспорт полных официальных записей без зависимости от состояния UI-классов."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3


def read_laureates(path, identifiers):
    """Прочитать уникальные ID пакетами через одно read-only соединение SQLite.

    Все поля raw_json сохраняются. Параметры передаются отдельно от SQL,
    а размер пакета 500 совместим с ограничением старых сборок SQLite.
    """
    ids = sorted(set(map(str, identifiers)))
    result = []
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        for start in range(0, len(ids), 500):
            batch = ids[start : start + 500]
            placeholders = ",".join("?" for _ in batch)
            rows = connection.execute(
                f"SELECT raw_json FROM laureates WHERE id IN ({placeholders}) ORDER BY id",
                batch,
            )
            result.extend(json.loads(row[0]) for row in rows)
    return result
