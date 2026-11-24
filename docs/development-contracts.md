# Общий контракт разработки

Этот документ описывает общую основу для параллельной разработки. Он не
реализует бизнес-логику и не заменяет ADR.

## Среда

- Python 3.13.
- FastAPI для Rental API.
- Асинхронные интерфейсы портов.
- Unit-тесты не требуют PostgreSQL, Redis или внешних HTTP-сервисов.

## Каталоги

- `app/domain` - сущности и статусы без HTTP, БД и Redis.
- `app/schemas` - Pydantic DTO публичного API.
- `app/ports` - интерфейсы репозиториев, клиентов внешних систем и кэша.
- `tests/fakes` - in-memory реализации портов для unit-тестов.
- `app/main.py` - точка запуска FastAPI и health/readiness checks.

## Зафиксированные API-контракты

- `POST /offers` - создание оффера.
- `POST /rentals` - старт аренды по офферу.
- `GET /rentals/{rental_id}` - просмотр аренды и накопленной стоимости.
- `POST /station-events/powerbank-returned` - внутреннее событие физического
  возврата пауэрбанка от `stations`.

Бизнес-реализация маршрутов будет добавляться отдельными PR. Изменение DTO или
сигнатуры порта требует согласования команды, потому что затрагивает несколько
параллельных веток.

## Локальная проверка

```bash
pipenv install --dev
pipenv run pytest tests/unit
pipenv run uvicorn app.main:app --reload
```

После запуска API доступны `GET /health` и `GET /ready`.
