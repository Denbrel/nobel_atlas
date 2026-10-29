"""Клиенты Nobel и Wikidata: запросы последовательны, ограничены по частоте и времени."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import wraps
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)


def timed(fn):
    """Декоратор журналирования времени, сохраняющий имя и документацию функции."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        """Измерить выполнение, включая неуспешное завершение."""
        start = time.monotonic()
        try:
            return fn(*args, **kwargs)
        finally:
            log.info("%s completed in %.2fs", fn.__name__, time.monotonic() - start)

    return wrapper


class PoliteHTTP:
    """Последовательный HTTP-клиент с паузами, таймаутами и ограниченными повторами."""

    def __init__(self, user_agent=None, interval=1.1, timeout=60, attempts=4):
        """Задать идентификацию клиента и пределы частоты/повторов запросов."""
        self.user_agent = user_agent or os.getenv(
            "NOBEL_USER_AGENT",
            "NobelAtlasCourseProject/2.0 (educational open-data client)",
        )
        self.interval = max(1.0, interval)
        self.timeout = timeout
        self.attempts = attempts
        self.last = 0.0

    def _pause(self):
        """Выдержать минимальный интервал между началами запросов."""
        time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
        self.last = time.monotonic()

    @staticmethod
    def retry_delay(value, attempt):
        """Разобрать Retry-After в секундах или HTTP-дате с запасной задержкой."""
        if value:
            try:
                delay = float(value)
            except ValueError:
                try:
                    delay = (
                        parsedate_to_datetime(value) - datetime.now(timezone.utc)
                    ).total_seconds()
                except (TypeError, ValueError):
                    delay = 0
            return max(0, delay, 2**attempt)
        return 2**attempt

    def get(self, url, params):
        """Получить JSON; повторять только временные сбои и учитывать указания сервера."""
        full = url + "?" + urllib.parse.urlencode(params)
        for attempt in range(self.attempts):
            self._pause()
            try:
                request = urllib.request.Request(
                    full,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "application/json",
                    },
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.load(response)
                if "error" in data:
                    if data["error"].get("code") in (
                        "maxlag",
                        "ratelimited",
                        "readonly",
                    ):
                        raise RuntimeError("API busy: " + data["error"].get("code", ""))
                    raise ValueError("API error: " + str(data["error"]))
                return data
            except urllib.error.HTTPError as exc:
                if (
                    exc.code not in (429, 500, 502, 503, 504)
                    or attempt + 1 == self.attempts
                ):
                    raise
                delay = self.retry_delay(exc.headers.get("Retry-After"), attempt)
            except (urllib.error.URLError, TimeoutError, ConnectionError, RuntimeError):
                if attempt + 1 == self.attempts:
                    raise
                delay = max(5, 2**attempt)
            if delay > 60:
                raise RuntimeError(
                    f"Server asks to wait {delay:.0f}s; retry this job later"
                )
            log.warning("Transient error; retry in %.1fs", delay)
            time.sleep(delay)
        raise RuntimeError("Retries exhausted")


class SourceClient(ABC):
    """Абстрактный интерфейс источника: наследники реализуют fetch."""

    def __init__(self, http=None):
        """Принять HTTP-клиент через композицию для повторного использования и тестов."""
        self.http = http or PoliteHTTP()

    @abstractmethod
    def fetch(self, *args, **kwargs):
        """Обязательный контракт получения данных для каждого конкретного источника."""
        raise NotImplementedError


class NobelClient(SourceClient):
    """Загрузка всех страниц официального Nobel API 2.1."""

    BASE = "https://api.nobelprize.org/2.1/"

    @timed
    def fetch(self, endpoint):
        """Проверять offset и count каждой страницы, не выдавая частичную загрузку за полную."""
        if endpoint not in ("laureates", "nobelPrizes"):
            raise ValueError("Unsupported Nobel endpoint")
        items, pages, offset, total = [], [], 0, None
        while total is None or len(items) < total:
            data = self.http.get(
                self.BASE + endpoint, {"limit": 1000, "offset": offset}
            )
            batch = data.get(endpoint)
            count = int(data["meta"]["count"])
            if not isinstance(batch, list) or not batch:
                raise ValueError("Incomplete page; old database will not be changed")
            if total is not None and count != total:
                raise ValueError("Source count changed during pagination")
            if int(data["meta"]["offset"]) != offset:
                raise ValueError("API returned the wrong offset")
            total = count
            items.extend(batch)
            pages.append(data)
            offset += len(batch)
            log.info("%s: %d / %d", endpoint, len(items), total)
        if len(items) != total:
            raise ValueError("Source count mismatch")
        return {"items": items, "pages": pages}


class WikidataClient(SourceClient):
    """Дополнительный источник описаний и утверждений с пакетами до 50 QID."""

    URL = "https://www.wikidata.org/w/api.php"

    @timed
    def fetch(self, ids):
        """Получить сущности вместе с утверждениями, квалификаторами и ссылками."""
        ids = sorted(set(x for x in ids if re.fullmatch(r"Q[1-9]\d*", x or "")))
        entities = {}
        for start in range(0, len(ids), 50):
            batch = ids[start : start + 50]
            payload = self.http.get(
                self.URL,
                {
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": "labels|descriptions|aliases|claims|sitelinks",
                    "languages": "ru|en",
                    "format": "json",
                    "maxlag": 5,
                },
            )
            result = payload.get("entities", {})
            if any(q not in result for q in batch):
                raise ValueError("Incomplete Wikidata batch")
            entities.update(result)
            log.info("Wikidata: %d / %d", min(start + 50, len(ids)), len(ids))
        return entities
