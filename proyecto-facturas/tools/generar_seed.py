"""Lee datos/CONTROL_PROVEEDORES_BASE.xlsx y genera db/03_seed.sql.

Uso (desde la carpeta del proyecto):   python tools/generar_seed.py
Necesita:  pip install openpyxl

Hojas que se usan:
    Proveedores    -> supplier
    Fechas         -> invoice (subtotal, IVA, total) e invoice_detail
                      (una línea por factura, con la tasa IVA 15 %)
    FACTURAS_CXP   -> fecha de vencimiento y pagos (plazos marcados con "P")
Hojas que se ignoran: Catergoria (mismo contenido que Fechas), PAGOS_CXP
(es un resumen calculado), CONSULTA_CXP y CHEQUES.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
EXCEL = ROOT / "datos" / "CONTROL_PROVEEDORES_BASE.xlsx"
SALIDA = ROOT / "db" / "03_seed.sql"

USER_ID = 2          # Contabilidad registra las facturas y los pagos
DEPARTMENT_ID = 1    # Purchasing
METHOD_ID = 2        # Bank transfer
RATE_15 = 1          # la única tasa del sistema: IVA 15 %
PRODUCT_GENERAL = 1  # el Excel no trae el detalle por producto


def dec(value):
    """Número de Excel -> Decimal con 2 decimales."""
    if not isinstance(value, (int, float)):
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q(value):
    """Texto -> literal SQL (con comillas) o NULL."""
    if value is None or str(value).strip() in ("", "-"):
        return "NULL"
    return "'" + " ".join(str(value).split()).replace("'", "''") + "'"


def rows(wb, sheet):
    return [r for r in wb[sheet].iter_rows(values_only=True)
            if any(v is not None for v in r)]


def to_date(value, swap=False):
    """Convierte fechas de Excel. swap=True corrige las fechas que Excel leyó
    como mes/día cuando en realidad estaban escritas día/mes (8/1 -> 1 de agosto)."""
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, (int, float)):
        d = date(1899, 12, 30) + timedelta(days=int(value))
    elif isinstance(value, str):
        day, month, year = (int(x) for x in value.split("/"))
        return date(year, month, day)
    else:
        return None
    return date(d.year, d.day, d.month) if swap else d


def main():
    wb = openpyxl.load_workbook(EXCEL, data_only=True)

    # ---------- Proveedores ----------
    suppliers = {}                                   # RUC -> (nombre, teléfono)
    for r in rows(wb, "Proveedores")[5:]:
        if isinstance(r[0], str) and r[0].strip().isdigit():
            suppliers[r[0].strip()] = (r[1], r[9])

    # ---------- Facturas con desglose (hoja Fechas) ----------
    invoices = {}                                    # (RUC, número) -> datos
    for r in rows(wb, "Fechas")[1:]:
        ruc, name, number, issued = r[0], r[1], r[2], r[3]
        if not number or not isinstance(ruc, str):
            continue                                 # filas vacías del final
        suppliers.setdefault(ruc, (name, None))
        vat = dec((r[8] or 0) + (r[9] or 0))
        total = dec(r[11])
        base0 = dec(r[7])
        invoices[(ruc, number)] = {                  # (una factura repetida se queda una vez)
            "issue": to_date(issued), "subtotal": total - vat, "vat": vat,
            "total": total, "base0": base0, "base15": total - vat - base0,
            "due": to_date(issued), "payments": [],
        }

    # ---------- Vencimientos y pagos (hoja FACTURAS_CXP) ----------
    for r in rows(wb, "FACTURAS_CXP")[2:]:
        ruc, name, number, credit = r[0], r[1], r[2], r[5]
        if not number:
            continue
        suppliers.setdefault(ruc, (name, None))
        issue = to_date(r[3], swap=credit is None)   # sin días de crédito = fecha mal leída
        inv = invoices.get((ruc, number))
        if inv is None:
            # Factura que solo está en FACTURAS_CXP: no hay desglose,
            # se asume que el total incluye IVA 15 %.
            total = dec(r[4])
            subtotal = (total / Decimal("1.15")).quantize(Decimal("0.01"), ROUND_HALF_UP)
            inv = invoices[(ruc, number)] = {
                "issue": issue, "subtotal": subtotal, "vat": total - subtotal,
                "total": total, "base0": Decimal("0.00"), "base15": subtotal,
                "due": issue, "payments": [],
            }
        if credit:                                   # con crédito: vence en la fecha de la hoja
            inv["due"] = to_date(r[18]) or inv["issue"]
        plazos = [(r[i], r[i + 1], r[i + 2]) for i in (6, 9, 12, 15) if r[i] is not None]
        paid = Decimal("0.00")
        for n, (value, when, mark) in enumerate(plazos):
            if mark != "P":
                continue
            amount = dec(value)
            pay_date = to_date(when) if isinstance(when, datetime) else inv["issue"]
            last_and_all_paid = n == len(plazos) - 1 and all(p[2] == "P" for p in plazos)
            if last_and_all_paid or paid + amount > inv["total"]:
                amount = inv["total"] - paid         # el último pago cuadra los centavos
            if amount > 0:
                inv["payments"].append((pay_date, amount))
                paid += amount
        inv["paid"] = paid

    # ---------- Escribir el SQL ----------
    out = [
        "-- =====================================================================",
        "--  03_seed.sql  ->  Datos iniciales (AUTOREPUESTOS CARMAX)",
        "--  ARCHIVO GENERADO por tools/generar_seed.py a partir de",
        "--  datos/CONTROL_PROVEEDORES_BASE.xlsx. No editar a mano.",
        "-- =====================================================================",
        "",
        "SET NAMES utf8mb4;      -- para que las tildes se guarden bien",
        "",
        "INSERT INTO tax_rate (tax_rate_id, rate_name, rate_percent) VALUES",
        "    (1, 'IVA 15%', 15.00);",
        "",
        "INSERT INTO payment_method (payment_method_id, method_name) VALUES",
        "    (1, 'Cash'), (2, 'Bank transfer'), (3, 'Card'), (4, 'Check');",
        "",
        "INSERT INTO department (department_id, department_name) VALUES",
        "    (1, 'Purchasing'), (2, 'Administration'), (3, 'Sales');",
        "",
        "INSERT INTO app_user (app_user_id, full_name, email, role) VALUES",
        "    (1, 'Administrador CARMAX', 'admin@carmax.local', 'Admin'),",
        "    (2, 'Contabilidad CARMAX', 'contabilidad@carmax.local', 'Accountant'),",
        "    (3, 'Consulta CARMAX', 'consulta@carmax.local', 'Viewer');",
        "",
        "INSERT INTO category (category_id, category_name) VALUES",
        "    (1, 'Repuestos automotrices');",
        "",
        "INSERT INTO product (product_id, product_name, category_id, unit_of_measure) VALUES",
        "    (1, 'Compra de repuestos automotrices', 1, 'global');",
        "",
        "INSERT INTO supplier (supplier_id, company_name, tax_id, phone, email) VALUES",
    ]
    supplier_id = {}
    lines = []
    for n, (ruc, (name, phone)) in enumerate(sorted(suppliers.items(), key=lambda s: s[1][0].upper()), 1):
        supplier_id[ruc] = n
        lines.append(f"    ({n}, {q(name)}, {q(ruc)}, {q(phone)}, NULL)")
    out.append(",\n".join(lines) + ";")

    inv_lines, det_lines, pay_lines = [], [], []
    ordered = sorted(invoices.items(), key=lambda kv: (kv[1]["issue"], kv[0][1]))
    for n, ((ruc, number), inv) in enumerate(ordered, 1):
        status = "Paid" if inv.get("paid") == inv["total"] else "Pending"
        inv_lines.append(
            f"    ({n}, {supplier_id[ruc]}, {USER_ID}, {DEPARTMENT_ID}, {q(number)}, "
            f"'{inv['issue']}', '{inv['due']}', {inv['subtotal']}, {inv['vat']}, "
            f"{inv['total']}, '{status}')")
        # Una sola línea por factura con la tasa IVA 15 %. Los montos (subtotal, IVA
        # y total) son los de la factura real, tal como están en el Excel.
        det_lines.append(
            f"    ({n}, {PRODUCT_GENERAL}, {RATE_15}, 1.00, {inv['subtotal']}, {inv['subtotal']})")
        for pay_date, amount in inv["payments"]:
            pay_lines.append(f"    ({n}, {USER_ID}, '{pay_date}', {amount}, {METHOD_ID})")

    out += [
        "",
        "INSERT INTO invoice (invoice_id, supplier_id, app_user_id, department_id, invoice_number,",
        "                     issue_date, due_date, subtotal, vat, total_amount, payment_status) VALUES",
        ",\n".join(inv_lines) + ";",
        "",
        "INSERT INTO invoice_detail (invoice_id, product_id, tax_rate_id, quantity, unit_price, line_total) VALUES",
        ",\n".join(det_lines) + ";",
        "",
        "INSERT INTO payment (invoice_id, app_user_id, payment_date, amount_paid, payment_method_id) VALUES",
        ",\n".join(pay_lines) + ";",
        "",
        "-- Las facturas impagas cuya fecha de vencimiento ya pasó quedan 'Overdue' (FR-12)",
        "CALL sp_mark_overdue_invoices();",
        "",
    ]
    SALIDA.write_text("\n".join(out), encoding="utf-8")
    print(f"{len(suppliers)} proveedores, {len(invoices)} facturas, "
          f"{len(det_lines)} líneas de detalle, {len(pay_lines)} pagos -> {SALIDA}")


if __name__ == "__main__":
    main()
