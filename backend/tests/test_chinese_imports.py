import csv
import io

import pytest
from app.services.business_import_service import (
    CHINESE_HEADERS,
    HEADERS,
    parse_file,
    template,
)


@pytest.mark.parametrize("kind", HEADERS)
@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_chinese_template_and_roundtrip(kind, fmt):
    raw = template(kind, fmt, "zh")
    values = {key: "样本" for key in HEADERS[kind]}
    if fmt == "csv":
        text = io.StringIO(newline="")
        writer = csv.writer(text)
        writer.writerow(CHINESE_HEADERS[kind])
        writer.writerow(values.values())
        raw = text.getvalue().encode("utf-8-sig")
    else:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(raw))
        wb.active.append(list(values.values()))
        output = io.BytesIO()
        wb.save(output)
        wb.close()
        raw = output.getvalue()
    assert parse_file(kind, "样本." + fmt, raw) == [values]


def test_chinese_values_keep_existing_protocol():
    raw = (
        ",".join(CHINESE_HEADERS["demands"]) + "\n2026-10-20,S001,上午,300,普通\n"
    ).encode("utf-8-sig")
    assert parse_file("demands", "需求.csv", raw)[0] == {
        "date": "2026-10-20",
        "store_code": "S001",
        "period": "MORNING",
        "quantity": "300",
        "priority": "NORMAL",
    }


def test_chinese_template_is_opt_in_for_legacy_clients():
    assert template("demands", "csv").decode("utf-8-sig").strip() == ",".join(
        HEADERS["demands"]
    )


def test_http_chinese_template(client):
    response = client.get("/api/v1/business-imports/templates/demands?language=zh")
    assert response.status_code == 200
    assert response.content.decode("utf-8-sig").strip() == ",".join(
        CHINESE_HEADERS["demands"]
    )


def test_chinese_display_reference_search(session):
    from app.models.store import Store
    from app.services.base import BaseService

    row = Store(code="ENGLISH_ID", name="岳麓片区验收门店")
    session.add(row)
    session.commit()
    service = BaseService(session)
    assert service.search_page(Store, 0, 20, f"门店-{row.id:03d}")[0].id == row.id
    assert service.search_page(Store, 0, 20, "岳麓片区")[0].id == row.id
    assert service.search_page(Store, 0, 20, "线路-001") == []
