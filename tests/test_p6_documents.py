"""Tests de documentos: subida real y descarga (RF-17) — Fase P6."""
import io
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from conftest import ADMIN_EMAIL, CLIENT_EMAIL, EMPLOYEE_EMAIL


def _pdf_file():
    return (io.BytesIO(b"%PDF-1.4\n%%EOF"), "test.pdf")


def _png_file():
    return (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20), "test.png")


def _exe_file():
    return (io.BytesIO(b"MZ\x90\x00" + b"\x00" * 20), "malware.exe")


def _jpeg_file():
    return (io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 20), "not-allowed.jpeg")


def _fake_pdf():
    return (io.BytesIO(b"NOT A PDF"), "fake.pdf")


@pytest.fixture
def upload_dir(app, tmp_path):
    path = tmp_path / "uploads"
    app.config["UPLOAD_DIR"] = str(path)
    return path


def _csrf_token(client):
    resp = client.get("/dashboard")
    return re.search(r'<meta name="csrf-token" content="([^"]+)"',
                     resp.get_data(as_text=True)).group(1)


def _upload(client, url, file_tuple, client_id, field="file"):
    data = {
        field: file_tuple,
        "csrf_token": _csrf_token(client),
        "client_id": str(client_id),
    }
    return client.post(url, data=data, content_type="multipart/form-data")


def _client_id(email):
    from app import models as m
    return m.Client.query.filter_by(email=email).one().id


def test_subir_documento_pdf(client, store, login_as, upload_dir):
    login_as(client, ADMIN_EMAIL)
    resp = _upload(client, "/documents/new", _pdf_file(), _client_id(CLIENT_EMAIL))
    assert resp.status_code == 302
    from app import models as m
    doc = m.TravelDocument.query.filter(m.TravelDocument.stored_name.isnot(None)).one()
    assert re.fullmatch(r"[0-9a-f]{32}\.pdf", doc.stored_name)
    saved_file = upload_dir / doc.stored_name
    assert saved_file.is_file()
    assert saved_file.read_bytes().startswith(b"%PDF")


def test_subir_documento_png(client, store, login_as, upload_dir):
    login_as(client, ADMIN_EMAIL)
    resp = _upload(client, "/documents/new", _png_file(), _client_id(CLIENT_EMAIL))
    assert resp.status_code == 302
    from app import models as m
    doc = m.TravelDocument.query.filter_by(file_name="test.png").one()
    assert re.fullmatch(r"[0-9a-f]{32}\.png", doc.stored_name)
    assert (upload_dir / doc.stored_name).is_file()


def test_subir_exe_rechazado(client, store, login_as, upload_dir):
    from app import models as m

    login_as(client, ADMIN_EMAIL)
    count_before = m.TravelDocument.query.count()
    resp = _upload(client, "/documents/new", _exe_file(), _client_id(CLIENT_EMAIL))
    assert resp.status_code == 302
    assert m.TravelDocument.query.count() == count_before
    assert not upload_dir.exists() or not list(upload_dir.iterdir())


def test_subir_extension_no_permitida_rechazado(client, store, login_as, upload_dir):
    from app import models as m

    login_as(client, ADMIN_EMAIL)
    count_before = m.TravelDocument.query.count()
    resp = _upload(client, "/documents/new", _jpeg_file(), _client_id(CLIENT_EMAIL))
    assert resp.status_code == 302
    assert m.TravelDocument.query.count() == count_before
    assert not upload_dir.exists() or not list(upload_dir.iterdir())


def test_subir_firma_falsa_rechazado(client, store, login_as, upload_dir):
    from app import models as m

    login_as(client, ADMIN_EMAIL)
    count_before = m.TravelDocument.query.count()
    resp = _upload(client, "/documents/new", _fake_pdf(), _client_id(CLIENT_EMAIL))
    assert resp.status_code == 302
    assert m.TravelDocument.query.count() == count_before
    assert not upload_dir.exists() or not list(upload_dir.iterdir())


def test_descarga_documento_ajeno_403(client, store, login_as, upload_dir):
    from app import models as m

    login_as(client, ADMIN_EMAIL)
    owner = m.Client.query.filter_by(email=CLIENT_EMAIL).one()
    other_client = m.Client.query.filter(m.Client.id != owner.id).first()
    assert other_client is not None
    _upload(client, "/documents/new", _pdf_file(), other_client.id)
    doc = m.TravelDocument.query.filter_by(file_name="test.pdf").one()
    login_as(client, CLIENT_EMAIL)
    resp = client.get(f"/documents/{doc.id}/download")
    assert resp.status_code == 403


def test_descarga_documento_propio_200(client, store, login_as, upload_dir):
    from app import models as m

    login_as(client, ADMIN_EMAIL)
    _upload(client, "/documents/new", _pdf_file(), _client_id(CLIENT_EMAIL))
    doc = m.TravelDocument.query.filter_by(file_name="test.pdf").one()
    login_as(client, CLIENT_EMAIL)
    resp = client.get(f"/documents/{doc.id}/download")
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF")


def test_eliminar_documento_solo_admin(client, login_as, upload_dir):
    from app import models as m

    login_as(client, ADMIN_EMAIL)
    _upload(client, "/documents/new", _pdf_file(), _client_id(CLIENT_EMAIL))
    doc = m.TravelDocument.query.filter_by(file_name="test.pdf").one()
    login_as(client, EMPLOYEE_EMAIL)
    resp = client.post(
        f"/documents/{doc.id}/delete",
        data={"csrf_token": _csrf_token(client)},
    )
    assert resp.status_code == 403
    assert m.TravelDocument.query.filter_by(id=doc.id).count() == 1
