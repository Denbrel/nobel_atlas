"""Необязательный HTTP API для n8n; работает отдельным процессом и только читает базу."""

from functools import lru_cache
import hmac
import json
import os
from pathlib import Path
from typing import Annotated, Literal
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from nobel.analysis import AnalyticsService, FilterSpec, prepare, csv_bytes
from nobel.storage import DatabaseRepository


async def authorize(x_api_key: Annotated[str | None, Header()] = None):
    """Проверить необязательный API-ключ сравнением с постоянным временем."""
    expected = os.getenv("NOBEL_API_KEY")
    if expected and not hmac.compare_digest(expected, x_api_key or ""):
        raise HTTPException(401, "Invalid API key")


app = FastAPI(
    title="Nobel Atlas API",
    version="2.0.0",
    description="Read-only local snapshot API. No endpoint starts scraping.",
    dependencies=[Depends(authorize)],
)


def repository():
    """Открыть нужную базу или вернуть HTTP 503 при недоступной схеме."""
    repo = DatabaseRepository(
        os.getenv("NOBEL_DB", str(Path(__file__).with_name("nobel_database.sqlite")))
    )
    if not repo.path.exists() or repo.metadata().get("schema_version") != 2:
        raise HTTPException(503, "Database unavailable or unsupported; run the updater")
    return repo


@lru_cache(maxsize=2)
def _load(path, stamp):
    """Кэшировать аналитический слой по пути и версии файла SQLite."""
    repo = DatabaseRepository(path)
    df, affiliations, _ = repo.read_frames()
    residences = repo.read_residences()
    return AnalyticsService(
        prepare(df, affiliations, repo.wikidata_cache(), residences),
        affiliations,
        residences,
    )


def service():
    """Получить общий для сайта и API сервис с актуальным снимком."""
    repo = repository()
    stat = repo.path.stat()
    return _load(str(repo.path), (stat.st_mtime_ns, stat.st_size))


def filters(
    q: Annotated[str, Query(max_length=300)] = "",
    year_from: Annotated[int, Query(ge=1901, le=2200)] = 1901,
    year_to: Annotated[int, Query(ge=1901, le=2200)] = 2200,
    category: Annotated[list[str] | None, Query()] = None,
    birth_country: Annotated[list[str] | None, Query()] = None,
    birth_city: Annotated[list[str] | None, Query()] = None,
    work_country: Annotated[list[str] | None, Query()] = None,
    work_city: Annotated[list[str] | None, Query()] = None,
    institution: Annotated[list[str] | None, Query()] = None,
    kind: Literal["person", "organization"] | None = None,
    age_from: Annotated[int, Query(ge=0, le=110)] = 0,
    age_to: Annotated[int, Query(ge=0, le=110)] = 110,
    include_unknown_age: bool = True,
):
    """Преобразовать проверенные HTTP-параметры в объект FilterSpec."""
    if year_from > year_to or age_from > age_to:
        raise HTTPException(422, "Reversed range")
    return FilterSpec(
        query=q,
        year_min=year_from,
        year_max=year_to,
        categories=category or [],
        birth_countries=birth_country or [],
        birth_cities=birth_city or [],
        work_countries=work_country or [],
        work_cities=work_city or [],
        institutions=institution or [],
        kinds=[kind] if kind else [],
        age_min=age_from,
        age_max=age_to,
        include_unknown_age=include_unknown_age,
    )


def records(df):
    """Преобразовать таблицу в JSON-совместимые записи; NaN становится null."""
    return json.loads(df.to_json(orient="records", force_ascii=False))


@app.get("/health")
def health():
    """Вернуть состояние сервера и дату установленного снимка."""
    return {"status": "ok", "snapshot": repository().metadata()["updated_at"]}


@app.get("/meta")
def meta():
    """Отдать метаданные и контрольную сумму для отслеживания обновлений."""
    return repository().metadata()


@app.get("/laureates")
def laureates(
    spec: Annotated[FilterSpec, Depends(filters)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Вернуть страницу уникальных лауреатов, подходящих под фильтры."""
    df = service().filter(spec)
    cols = [
        "laureate_id",
        "name",
        "kind",
        "gender",
        "birth_date",
        "death_date",
        "birth_city",
        "birth_country",
        "description",
        "nobel_url",
        "wikidata_id",
    ]
    rows = df[cols].drop_duplicates("laureate_id").sort_values("name")
    return {
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "items": records(rows.iloc[offset : offset + limit]),
    }


@app.get("/laureates/{identifier}")
def laureate(identifier: str):
    """Получить все официальные поля одного лауреата или ответ 404."""
    raw = repository().raw_laureate(identifier)
    if raw is None:
        raise HTTPException(404, "Laureate not found")
    return {"source": "Nobel Prize API 2.1", "data": raw}


@app.get("/awards")
def awards(
    spec: Annotated[FilterSpec, Depends(filters)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Вернуть страницу награждений в порядке от новых к старым."""
    df = (
        service()
        .filter(spec)
        .sort_values(["award_year", "award_key"], ascending=[False, True])
    )
    return {
        "total": len(df),
        "offset": offset,
        "limit": limit,
        "items": records(
            df.drop(columns=["raw_json", "search_text"]).iloc[offset : offset + limit]
        ),
    }


@app.get("/stats")
def stats(spec: Annotated[FilterSpec, Depends(filters)]):
    """Посчитать лауреатов, награждения и премии как разные единицы."""
    df = service().filter(spec)
    return {
        "laureates": int(df.laureate_id.nunique()),
        "award_credits": len(df),
        "prizes": int(df.prize_key.nunique()),
        "categories": df.groupby("category").size().to_dict(),
        "by_year": {str(k): int(v) for k, v in df.groupby("award_year").size().items()},
    }


@app.get("/export.csv")
def export(spec: Annotated[FilterSpec, Depends(filters)]):
    """Скачать отфильтрованную таблицу с защитой CSV от формул."""
    df = service().filter(spec).drop(columns=["raw_json", "search_text"])
    return Response(
        csv_bytes(df),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=nobel.csv"},
    )
