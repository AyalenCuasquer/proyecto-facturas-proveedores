"""Casos de prueba TC-01 a TC-11 (Sección 4 del documento de diseño).

Cómo ejecutarlos (con el contenedor mysql-facturas encendido):

    python -m pytest tests -v

Las pruebas NO tocan los datos reales: crean una base aparte llamada
invoice_db_test con el mismo esquema (db/01_schema.sql y db/02_views_events.sql),
y la borran al terminar.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pymysql
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import config                      # noqa: E402
from app import create_app         # noqa: E402

TEST_DB = "invoice_db_test"
TABLES = ["payment", "invoice_detail", "invoice", "product", "payment_method",
          "tax_rate", "category", "department", "app_user", "supplier"]


def connect(database=None):
    return pymysql.connect(
        host=config.DB_HOST, port=int(config.DB_PORT), user=config.DB_USER,
        password=config.DB_PASSWORD, database=database, autocommit=True,
        charset="utf8mb4",
    )


def run_sql_file(cursor, path):
    """Ejecuta un archivo .sql sentencia por sentencia."""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if not ln.strip().startswith("--")]
    for statement in "\n".join(lines).split(";"):
        if statement.strip():
            cursor.execute(statement)


@pytest.fixture(scope="session")
def schema():
    """Crea la base de pruebas una sola vez y la borra al final."""
    conn = connect()
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    cur.execute(f"CREATE DATABASE {TEST_DB}")
    cur.execute(f"USE {TEST_DB}")
    run_sql_file(cur, ROOT / "db" / "01_schema.sql")
    run_sql_file(cur, ROOT / "db" / "02_views_events.sql")
    yield
    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    conn.close()


@pytest.fixture
def sql(schema):
    """Conexión directa a MySQL. Antes de cada prueba vacía las tablas y
    carga los datos mínimos (ids fijos para que las pruebas sean fáciles de leer)."""
    conn = connect(TEST_DB)
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    for table in TABLES:
        cur.execute(f"TRUNCATE TABLE {table}")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    cur.execute("INSERT INTO supplier VALUES "
                "(1, 'Papelería Andina S.A.', '1790012345001', '022345678', 'ventas@andina.ec')")
    cur.execute("INSERT INTO app_user VALUES (1, 'Ana Contadora', 'ana@empresa.ec', 'Accountant')")
    cur.execute("INSERT INTO department VALUES (1, 'Administration'), (2, 'Sales')")
    cur.execute("INSERT INTO category VALUES (1, 'Office supplies')")
    cur.execute("INSERT INTO tax_rate VALUES (1, 'IVA 15%', 15)")
    cur.execute("INSERT INTO payment_method VALUES "
                "(1, 'Cash'), (2, 'Bank transfer'), (3, 'Card'), (4, 'Check')")
    cur.execute("INSERT INTO product VALUES (1, 'Resma de papel A4', 1, 'caja')")
    yield cur
    conn.close()


@pytest.fixture
def client(sql):
    """Cliente para llamar a la API sin tener que encender el servidor."""
    app = create_app(config.database_uri(TEST_DB))
    return app.test_client()


def new_invoice(client, number, subtotal, vat, total=None, issue="2026-10-10",
                due="2026-12-31", department_id=1, supplier_id=1):
    """Atajo: registra una factura por la API y devuelve la respuesta."""
    return client.post("/invoices", json={
        "supplier_id": supplier_id, "department_id": department_id, "app_user_id": 1,
        "invoice_number": number, "issue_date": issue, "due_date": due,
        "subtotal": subtotal, "vat": vat,
        "total_amount": total if total is not None else subtotal + vat,
    })


def pay(client, invoice_id, amount):
    return client.post(f"/invoices/{invoice_id}/payments", json={
        "app_user_id": 1, "payment_method_id": 2, "amount_paid": amount,
        "payment_date": "2026-11-01",
    })


# ----------------------------------------------------------------------
def test_tc01_proveedor_con_ruc_duplicado(client):
    r = client.post("/suppliers", json={"company_name": "Otro proveedor",
                                        "tax_id": "1790012345001"})
    assert r.status_code == 409
    assert "uq_supplier_tax_id" in r.json["detail"]


def test_tc02_numero_de_factura_duplicado(client):
    assert new_invoice(client, "F-001-2026", 100, 15).status_code == 201
    r = new_invoice(client, "F-001-2026", 200, 30)
    assert r.status_code == 409
    assert "uq_invoice_invoice_number" in r.json["detail"]


def test_tc03_total_debe_ser_subtotal_mas_iva(client):
    r = new_invoice(client, "F-003", 100.00, 15.00, total=130.00)
    assert r.status_code == 400
    assert "ck_invoice_total_equals_subtotal_plus_vat" in r.json["detail"]


def test_tc04_filtrar_por_estado_de_pago(client):
    pending = new_invoice(client, "F-PEND", 100, 15).json
    paid = new_invoice(client, "F-PAID", 200, 30).json
    pay(client, paid["invoice_id"], 230)
    r = client.get("/invoices?status=Pending")
    assert [i["invoice_id"] for i in r.json] == [pending["invoice_id"]]
    assert all(i["payment_status"] == "Pending" for i in r.json)


def test_tc05_reporte_de_gasto_e_iva_del_periodo(client):
    new_invoice(client, "F-OCT-1", 100.00, 15.00, issue="2026-10-05")
    new_invoice(client, "F-OCT-2", 200.00, 30.00, issue="2026-10-20")
    new_invoice(client, "F-NOV-1", 500.00, 75.00, issue="2026-11-03")
    r = client.get("/reports/expenses?date_from=2026-10-01&date_to=2026-10-31")
    assert r.json["total_expense"] == 345.00
    assert r.json["total_vat"] == 45.00


def test_tc06_dos_pagos_parciales_cancelan_la_factura(client):
    invoice = new_invoice(client, "F-006", 100, 15).json
    assert invoice["payment_status"] == "Pending"
    assert pay(client, invoice["invoice_id"], 100.00).status_code == 201
    assert pay(client, invoice["invoice_id"], 15.00).status_code == 201
    result = client.get(f"/invoices/{invoice['invoice_id']}").json
    assert result["total_paid"] == 115.00
    assert result["payment_status"] == "Paid"


def test_tc07_pago_no_puede_superar_el_total(client):
    invoice = new_invoice(client, "F-007", 100, 15).json
    pay(client, invoice["invoice_id"], 100.00)
    r = pay(client, invoice["invoice_id"], 50.00)
    assert r.status_code == 400
    assert "Monto excedido" in r.json["error"]
    assert client.get(f"/invoices/{invoice['invoice_id']}").json["total_paid"] == 100.00


def test_tc08_pago_con_monto_no_positivo(client):
    invoice = new_invoice(client, "F-008", 100, 15).json
    r = pay(client, invoice["invoice_id"], -10.00)
    assert r.status_code == 400
    assert "ck_payment_amount_positive" in r.json["detail"]


def test_tc09_factura_sin_usuario_o_sin_departamento(sql):
    insert = ("INSERT INTO invoice (supplier_id, app_user_id, department_id, invoice_number,"
              " issue_date, due_date, subtotal, vat, total_amount)"
              " VALUES (1, %s, %s, 'F-009', '2026-10-10', '2026-12-31', 100, 15, 115)")
    with pytest.raises(pymysql.err.IntegrityError, match="app_user_id.*cannot be null"):
        sql.execute(insert, (None, 1))
    with pytest.raises(pymysql.err.IntegrityError, match="department_id.*cannot be null"):
        sql.execute(insert, (1, None))


def test_tc10_facturas_vencidas_se_marcan_solas(sql):
    today = date.today()
    issue = today - timedelta(days=30)
    insert = ("INSERT INTO invoice (supplier_id, app_user_id, department_id, invoice_number,"
              " issue_date, due_date, subtotal, vat, total_amount, payment_status)"
              " VALUES (1, 1, 1, %s, %s, %s, 100, 15, 115, %s)")
    sql.execute(insert, ("A", issue, today - timedelta(days=5), "Pending"))
    sql.execute(insert, ("B", issue, today + timedelta(days=5), "Pending"))
    sql.execute(insert, ("C", issue, today - timedelta(days=5), "Paid"))
    # El evento existe, está activo y se ejecuta cada día
    sql.execute("SELECT status, interval_value, interval_field FROM information_schema.events"
                " WHERE event_schema = DATABASE() AND event_name = 'evt_mark_overdue_invoices'")
    assert sql.fetchone() == ("ENABLED", "1", "DAY")
    # Se ejecuta lo mismo que hace el evento
    sql.execute("CALL sp_mark_overdue_invoices()")
    sql.execute("SELECT invoice_number, payment_status FROM invoice ORDER BY invoice_number")
    assert dict(sql.fetchall()) == {"A": "Overdue", "B": "Pending", "C": "Paid"}


def test_tc11_saldo_pendiente_del_proveedor(client, sql):
    first = new_invoice(client, "F-011-1", 100, 15).json      # 115.00
    new_invoice(client, "F-011-2", 200, 30)                    # 230.00
    pay(client, first["invoice_id"], 100.00)
    sql.execute("SELECT pending_balance FROM vw_supplier_balance WHERE supplier_id = 1")
    assert float(sql.fetchone()[0]) == 245.00
    r = client.get("/reports/supplier-balance?supplier_id=1")
    assert r.json[0]["pending_balance"] == 245.00
