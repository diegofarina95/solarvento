"""Tests del almacén de programaciones del blog (app/blog_schedule.py)."""

from datetime import datetime

import pytest

from app import blog_schedule


@pytest.fixture(autouse=True)
def schedule_file(monkeypatch, tmp_path):
    f = tmp_path / "schedule.json"
    monkeypatch.setattr(blog_schedule, "SCHEDULE_FILE", f)
    return f


def test_parse_local():
    assert blog_schedule.parse_local("2026-07-09T09:00") == datetime(2026, 7, 9, 9, 0)
    assert blog_schedule.parse_local("2026-07-09 09:00") is None
    assert blog_schedule.parse_local("") is None
    assert blog_schedule.parse_local(None) is None


def test_set_get_remove():
    blog_schedule.set_schedule("factura", "2026-07-09T09:00")
    assert blog_schedule.get("factura") == {
        "publish_at": "2026-07-09T09:00", "state": "pending", "error": None,
    }
    blog_schedule.remove("factura")
    assert blog_schedule.get("factura") is None
    blog_schedule.remove("factura")  # idempotente


def test_set_sobrescribe_y_resetea_estado():
    blog_schedule.set_schedule("factura", "2026-07-09T09:00")
    blog_schedule.mark_error("factura", "rsync caído")
    blog_schedule.set_schedule("factura", "2026-07-10T09:00")  # reprogramar limpia el error
    assert blog_schedule.get("factura") == {
        "publish_at": "2026-07-10T09:00", "state": "pending", "error": None,
    }


def test_load_sin_archivo_es_vacio():
    assert blog_schedule.load() == {}


def test_load_json_corrupto_es_vacio(schedule_file):
    schedule_file.write_text("{no es json")
    assert blog_schedule.load() == {}
    schedule_file.write_text('["lista", "no", "dict"]')
    assert blog_schedule.load() == {}


def test_load_filtra_entradas_invalidas(schedule_file):
    schedule_file.write_text(
        '{"buena": {"publish_at": "2026-07-09T09:00", "state": "pending"},'
        ' "sin-hora": {"state": "pending"},'
        ' "hora-mala": {"publish_at": "mañana", "state": "pending"},'
        ' "estado-malo": {"publish_at": "2026-07-09T09:00", "state": "volando"},'
        ' "no-dict": 7}'
    )
    assert list(blog_schedule.load()) == ["buena"]


def test_due_solo_pending_vencidas():
    blog_schedule.set_schedule("b-luego", "2026-07-09T09:00")
    blog_schedule.set_schedule("a-ya", "2026-07-08T09:00")
    blog_schedule.set_schedule("c-ya", "2026-07-08T08:00")
    blog_schedule.mark_error("c-ya", "boom")  # error: nunca due
    assert blog_schedule.due(datetime(2026, 7, 8, 12, 0)) == ["a-ya"]
    assert blog_schedule.due(datetime(2026, 7, 9, 9, 0)) == ["a-ya", "b-luego"]


def test_mark_stale_before_solo_pending_anteriores():
    blog_schedule.set_schedule("vieja", "2026-07-08T09:00")
    blog_schedule.set_schedule("futura", "2026-07-10T09:00")
    blog_schedule.mark_stale_before(datetime(2026, 7, 9, 0, 0))
    assert blog_schedule.get("vieja")["state"] == "stale"
    assert blog_schedule.get("futura")["state"] == "pending"
    # una stale no vuelve a transicionar ni entra en due()
    assert blog_schedule.due(datetime(2026, 7, 30, 0, 0)) == ["futura"]


def test_mark_error_guarda_mensaje():
    blog_schedule.set_schedule("factura", "2026-07-09T09:00")
    blog_schedule.mark_error("factura", "rsync: connection refused")
    entry = blog_schedule.get("factura")
    assert entry["state"] == "error"
    assert entry["error"] == "rsync: connection refused"
    blog_schedule.mark_error("no-existe", "x")  # no crea entradas fantasma
    assert blog_schedule.get("no-existe") is None
