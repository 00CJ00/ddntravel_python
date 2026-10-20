"""Tests de reportes PDF/XLSX (RF-15) — Fase P5."""
import os
import sys

import pytest
from openpyxl import load_workbook

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from conftest import ADMIN_EMAIL, EMPLOYEE_EMAIL, CLIENT_EMAIL


def test_reporte_bookings_pdf(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = client.get("/reports/bookings.pdf")
    assert resp.status_code == 200
    assert resp.data[:5] == b"%PDF-"


def test_reporte_bookings_xlsx(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = client.get("/reports/bookings.xlsx")
    assert resp.status_code == 200
    assert "spreadsheet" in resp.mimetype


def test_reporte_clients_pdf(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = client.get("/reports/clients.pdf")
    assert resp.status_code == 200
    assert resp.data[:5] == b"%PDF-"


def test_reporte_occupancy_xlsx(client, login_as):
    from io import BytesIO
    login_as(client, ADMIN_EMAIL)
    resp = client.get("/reports/occupancy.xlsx")
    assert resp.status_code == 200
    wb = load_workbook(BytesIO(resp.data))
    assert wb.active is not None


def test_reporte_tipo_invalido_422(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = client.get("/reports/inventario.pdf")
    assert resp.status_code == 422


def test_reporte_formato_invalido_422(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = client.get("/reports/bookings.csv")
    assert resp.status_code == 422


def test_reporte_cliente_403(client, login_as):
    login_as(client, CLIENT_EMAIL)
    resp = client.get("/reports/bookings.pdf")
    assert resp.status_code == 403


def test_reporte_empleado_200(client, login_as):
    login_as(client, EMPLOYEE_EMAIL)
    resp = client.get("/reports/bookings.xlsx")
    assert resp.status_code == 200
