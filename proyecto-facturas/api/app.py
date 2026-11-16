"""API del Sistema de Gestión de Facturas de Proveedores (Flask + SQLAlchemy).

Para ejecutarla:   python app.py     ->   http://127.0.0.1:5000
Interfaz gráfica:  http://127.0.0.1:5000/app   (archivos de la carpeta gui/)

Resumen de rutas
----------------
Catálogos (GET lista, POST crea, GET/PUT/DELETE por id):
    /suppliers  /users  /departments  /categories  /tax-rates
    /payment-methods  /products
    La lista acepta ?q=texto (búsqueda), ?limit= y ?offset= (paginación);
    /products acepta además ?category_id=. El total de filas encontradas
    se devuelve en la cabecera X-Total-Count.
Facturas:
    GET    /invoices            buscar (supplier_id, status, date_from, date_to, department_id)
    POST   /invoices            registrar una factura (con o sin líneas de detalle)
    GET    /invoices/<id>       una factura con sus detalles, pagos y saldo
    DELETE /invoices/<id>       borrar una factura sin pagos
    POST   /invoices/<id>/details    agregar una línea de detalle
    GET    /invoices/<id>/payments   pagos de la factura
    POST   /invoices/<id>/payments   registrar un pago (total o parcial)
    POST   /invoices/mark-overdue    marcar las vencidas ahora mismo
Reportes:
    GET /reports/expenses?date_from=&date_to=              (FR-05)
    GET /reports/supplier-balance[?supplier_id=]           (FR-13)
    GET /reports/department-expenses?date_from=&date_to=   (FR-14)
    GET /reports/summary                                   (resumen para la pantalla inicial)
"""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import func, or_, text
from sqlalchemy.exc import DBAPIError

from config import database_uri
from models import (
    db, money, Supplier, AppUser, Department, Category, TaxRate,
    PaymentMethod, Product, Invoice, InvoiceDetail, Payment,
)


# Carpeta con los archivos de la interfaz gráfica (HTML, CSS y JavaScript)
GUI_DIR = Path(__file__).resolve().parent.parent / "gui"


# ----------------------------------------------------------------------
# Funciones de ayuda
# ----------------------------------------------------------------------
class ApiError(Exception):
    """Error que se devuelve al cliente como JSON: {"error": "..."}"""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def get_json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("El cuerpo de la petición debe ser un JSON.")
    return data


def require(data, fields):
    """Revisa que el JSON traiga todos los campos obligatorios."""
    missing = [f for f in fields if data.get(f) in (None, "")]
    if missing:
        raise ApiError("Faltan campos obligatorios: " + ", ".join(missing))


def to_decimal(value, field):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ApiError(f"El campo '{field}' debe ser un número.")


def to_date(value, field):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ApiError(f"El campo '{field}' debe ser una fecha AAAA-MM-DD.")


def to_int(value, field):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ApiError(f"El parámetro '{field}' debe ser un número entero.")
    if number < 0:
        raise ApiError(f"El parámetro '{field}' no puede ser negativo.")
    return number


def round2(value):
    """Redondea a 2 decimales (centavos)."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_or_404(model, record_id):
    record = db.session.get(model, record_id)
    if record is None:
        raise ApiError(f"No existe {model.__tablename__} con id {record_id}.", 404)
    return record


def build_detail(line):
    """Crea una línea de detalle a partir del JSON. line_total = cantidad x precio."""
    require(line, ["product_id", "tax_rate_id", "quantity", "unit_price"])
    quantity = to_decimal(line["quantity"], "quantity")
    unit_price = to_decimal(line["unit_price"], "unit_price")
    return InvoiceDetail(
        product_id=line["product_id"],
        tax_rate_id=line["tax_rate_id"],
        quantity=quantity,
        unit_price=unit_price,
        line_total=round2(quantity * unit_price),
    )


def totals_from_details(details):
    """Calcula subtotal e IVA sumando las líneas; cada línea usa SU tasa (FR-07)."""
    subtotal = Decimal("0")
    vat = Decimal("0")
    for d in details:
        rate = db.session.get(TaxRate, d.tax_rate_id)
        if rate is None:
            raise ApiError(f"No existe tax_rate con id {d.tax_rate_id}.")
        subtotal += d.line_total
        vat += round2(d.line_total * rate.rate_percent / 100)
    return subtotal, vat


def refresh_status(invoice):
    """Pone el estado correcto según lo pagado y la fecha de vencimiento."""
    if invoice.total_amount > 0 and invoice.total_paid() >= invoice.total_amount:
        invoice.payment_status = "Paid"
    elif invoice.due_date < date.today():
        invoice.payment_status = "Overdue"
    else:
        invoice.payment_status = "Pending"


# ----------------------------------------------------------------------
# Creación de la aplicación
# ----------------------------------------------------------------------
def create_app(db_uri=None):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri or database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.json.ensure_ascii = False       # para que las tildes salgan bien
    app.json.sort_keys = False
    db.init_app(app)

    # ---------------- Manejo de errores ----------------
    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify({"error": err.message}), err.status

    @app.errorhandler(DBAPIError)
    def handle_db_error(err):
        """Traduce los errores de MySQL (UNIQUE, FK, CHECK, NOT NULL) a JSON."""
        db.session.rollback()
        code = err.orig.args[0] if err.orig.args else None
        detail = str(err.orig.args[1]) if len(err.orig.args) > 1 else str(err.orig)
        messages = {
            1062: ("Registro duplicado (restricción UNIQUE)", 409),
            1452: ("Se hace referencia a un registro que no existe (clave foránea)", 400),
            1451: ("No se puede borrar: otros registros dependen de este (clave foránea)", 409),
            1048: ("Falta un campo obligatorio (NOT NULL)", 400),
            3819: ("Dato inválido: no cumple una restricción CHECK", 400),
            1406: ("Un texto es demasiado largo para su columna", 400),
            1264: ("Un número está fuera del rango permitido", 400),
        }
        message, status = messages.get(code, ("Error de base de datos", 500))
        return jsonify({"error": message, "mysql_code": code, "detail": detail}), status

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify({"error": "Ruta no encontrada."}), 404

    @app.get("/")
    def index():
        return jsonify({
            "api": "Sistema de Gestión de Facturas de Proveedores",
            "rutas": sorted(
                f"{', '.join(sorted(r.methods - {'HEAD', 'OPTIONS'}))} {r.rule}"
                for r in app.url_map.iter_rules() if r.endpoint != "static"
            ),
        })

    # ---------------- Interfaz gráfica (GUI) ----------------
    @app.get("/app")
    @app.get("/app/")
    def gui_index():
        return send_from_directory(GUI_DIR, "index.html")

    @app.get("/app/<path:filename>")
    def gui_file(filename):
        return send_from_directory(GUI_DIR, filename)

    # ---------------- Catálogos (CRUD sencillo) ----------------
    def register_catalog(url, model, required, optional=(), search=(), filters=(), order=None):
        """Crea las 5 rutas básicas (listar, crear, ver, editar, borrar) de una tabla.

        search  = columnas de texto donde busca ?q=
        filters = columnas que se pueden filtrar con ?columna=valor
        order   = columna para ordenar la lista (por defecto la clave primaria)
        """
        pk = model.__table__.primary_key.columns.keys()[0]
        fields = list(required) + list(optional)
        name = model.__tablename__

        def list_all():
            args = request.args
            query = db.select(model)
            if args.get("q") and search:
                pattern = f"%{args['q'].strip()}%"
                query = query.where(or_(*[getattr(model, f).like(pattern) for f in search]))
            for f in filters:
                if args.get(f):
                    query = query.where(getattr(model, f) == args[f])
            total = db.session.scalar(db.select(func.count()).select_from(query.subquery()))
            query = query.order_by(getattr(model, order or pk), getattr(model, pk))
            if args.get("limit"):
                query = query.limit(to_int(args["limit"], "limit"))
                query = query.offset(to_int(args.get("offset", 0), "offset"))
            response = jsonify([r.to_dict() for r in db.session.scalars(query)])
            response.headers["X-Total-Count"] = str(total)
            return response

        def create():
            data = get_json()
            require(data, required)
            record = model(**{f: data.get(f) for f in fields})
            db.session.add(record)
            db.session.commit()
            return jsonify(record.to_dict()), 201

        def get_one(record_id):
            return jsonify(get_or_404(model, record_id).to_dict())

        def update(record_id):
            record = get_or_404(model, record_id)
            data = get_json()
            for f in fields:
                if f in data:
                    setattr(record, f, data[f])
            db.session.commit()
            return jsonify(record.to_dict())

        def delete(record_id):
            record = get_or_404(model, record_id)
            db.session.delete(record)
            db.session.commit()
            return jsonify({"message": f"{name} {record_id} eliminado."})

        app.add_url_rule(url, f"list_{name}", list_all, methods=["GET"])
        app.add_url_rule(url, f"create_{name}", create, methods=["POST"])
        app.add_url_rule(f"{url}/<int:record_id>", f"get_{name}", get_one, methods=["GET"])
        app.add_url_rule(f"{url}/<int:record_id>", f"update_{name}", update, methods=["PUT"])
        app.add_url_rule(f"{url}/<int:record_id>", f"delete_{name}", delete, methods=["DELETE"])

    register_catalog("/suppliers", Supplier, ["company_name", "tax_id"], ["phone", "email"],
                     search=["company_name", "tax_id"])                                       # FR-01
    register_catalog("/users", AppUser, ["full_name", "email", "role"])                       # FR-10
    register_catalog("/departments", Department, ["department_name"])                         # FR-11
    register_catalog("/categories", Category, ["category_name"])
    register_catalog("/tax-rates", TaxRate, ["rate_name", "rate_percent"])
    register_catalog("/payment-methods", PaymentMethod, ["method_name"])
    register_catalog("/products", Product, ["product_name", "category_id", "unit_of_measure"],
                     search=["product_name"], filters=["category_id"],
                     order="product_name")                                                    # FR-06

    # ---------------- Facturas ----------------
    @app.get("/invoices")
    def list_invoices():
        """FR-04: buscar facturas por proveedor, fecha, estado o departamento."""
        query = db.select(Invoice)
        args = request.args
        if args.get("supplier_id"):
            query = query.where(Invoice.supplier_id == args["supplier_id"])
        if args.get("department_id"):
            query = query.where(Invoice.department_id == args["department_id"])
        if args.get("status"):
            query = query.where(Invoice.payment_status == args["status"])
        if args.get("invoice_number"):
            query = query.where(Invoice.invoice_number == args["invoice_number"])
        if args.get("date_from"):
            query = query.where(Invoice.issue_date >= to_date(args["date_from"], "date_from"))
        if args.get("date_to"):
            query = query.where(Invoice.issue_date <= to_date(args["date_to"], "date_to"))
        rows = db.session.scalars(query.order_by(Invoice.issue_date, Invoice.invoice_id))
        return jsonify([r.to_dict() for r in rows])

    @app.post("/invoices")
    def create_invoice():
        """FR-02 / FR-07: registrar una factura.

        - Con "details": el subtotal, el IVA y el total se calculan de las líneas.
        - Sin "details": hay que enviar subtotal, vat y total_amount.
        """
        data = get_json()
        require(data, ["supplier_id", "department_id", "app_user_id",
                       "invoice_number", "issue_date", "due_date"])
        invoice = Invoice(
            supplier_id=data["supplier_id"],
            department_id=data["department_id"],
            app_user_id=data["app_user_id"],
            invoice_number=data["invoice_number"],
            issue_date=to_date(data["issue_date"], "issue_date"),
            due_date=to_date(data["due_date"], "due_date"),
        )
        lines = data.get("details") or []
        if lines:
            invoice.details = [build_detail(line) for line in lines]
            invoice.subtotal, invoice.vat = totals_from_details(invoice.details)
            invoice.total_amount = invoice.subtotal + invoice.vat
            # Si además enviaron los montos, deben coincidir con las líneas
            for field in ("subtotal", "vat", "total_amount"):
                if field in data and to_decimal(data[field], field) != getattr(invoice, field):
                    raise ApiError(
                        f"El campo '{field}' ({data[field]}) no coincide con la suma "
                        f"de las líneas de detalle ({getattr(invoice, field)})."
                    )
        else:
            require(data, ["subtotal", "vat", "total_amount"])
            invoice.subtotal = to_decimal(data["subtotal"], "subtotal")
            invoice.vat = to_decimal(data["vat"], "vat")
            invoice.total_amount = to_decimal(data["total_amount"], "total_amount")
        refresh_status(invoice)
        db.session.add(invoice)
        db.session.commit()      # aquí MySQL revisa UNIQUE, FK y CHECK
        return jsonify(invoice.to_dict(full=True)), 201

    @app.get("/invoices/<int:invoice_id>")
    def get_invoice(invoice_id):
        return jsonify(get_or_404(Invoice, invoice_id).to_dict(full=True))

    @app.delete("/invoices/<int:invoice_id>")
    def delete_invoice(invoice_id):
        invoice = get_or_404(Invoice, invoice_id)
        if invoice.payments:
            raise ApiError("No se puede borrar una factura que ya tiene pagos.", 409)
        db.session.delete(invoice)       # sus líneas de detalle se borran con ella
        db.session.commit()
        return jsonify({"message": f"Factura {invoice_id} eliminada."})

    @app.post("/invoices/<int:invoice_id>/details")
    def add_detail(invoice_id):
        """Agrega una línea de detalle y recalcula los totales de la factura."""
        invoice = get_or_404(Invoice, invoice_id)
        invoice.details.append(build_detail(get_json()))
        subtotal, vat = totals_from_details(invoice.details)
        if subtotal + vat < invoice.total_paid():
            raise ApiError("El nuevo total sería menor que lo que ya se pagó.")
        invoice.subtotal, invoice.vat = subtotal, vat
        invoice.total_amount = subtotal + vat
        refresh_status(invoice)
        db.session.commit()
        return jsonify(invoice.to_dict(full=True)), 201

    # ---------------- Pagos ----------------
    @app.get("/invoices/<int:invoice_id>/payments")
    def list_invoice_payments(invoice_id):
        invoice = get_or_404(Invoice, invoice_id)
        return jsonify([p.to_dict() for p in invoice.payments])

    @app.post("/invoices/<int:invoice_id>/payments")
    def create_payment(invoice_id):
        """FR-08 / FR-09: registrar un pago total o parcial.

        La suma de pagos no puede pasar del total de la factura.
        Cuando la suma iguala el total, la factura queda 'Paid'.
        """
        data = get_json()
        require(data, ["app_user_id", "payment_method_id", "amount_paid"])
        # with_for_update bloquea la factura mientras se registra el pago,
        # así dos pagos al mismo tiempo no pueden pasarse del total.
        invoice = db.session.scalar(
            db.select(Invoice).where(Invoice.invoice_id == invoice_id).with_for_update()
        )
        if invoice is None:
            raise ApiError(f"No existe invoice con id {invoice_id}.", 404)

        amount = to_decimal(data["amount_paid"], "amount_paid")
        already_paid = invoice.total_paid()
        if already_paid + amount > invoice.total_amount:
            raise ApiError(
                "Monto excedido: la factura tiene un saldo pendiente de "
                f"{invoice.total_amount - already_paid} y se intentó pagar {amount}.",
                400,
            )
        payment = Payment(
            invoice=invoice,
            app_user_id=data["app_user_id"],
            payment_method_id=data["payment_method_id"],
            amount_paid=amount,
            payment_date=to_date(data.get("payment_date") or date.today(), "payment_date"),
        )
        db.session.add(payment)
        db.session.flush()       # aquí MySQL revisa ck_payment_amount_positive y las FK
        refresh_status(invoice)
        db.session.commit()
        return jsonify({"payment": payment.to_dict(),
                        "invoice": invoice.to_dict(full=True)}), 201

    @app.get("/payments")
    def list_payments():
        rows = db.session.scalars(db.select(Payment).order_by(Payment.payment_date))
        return jsonify([p.to_dict() for p in rows])

    @app.post("/invoices/mark-overdue")
    def mark_overdue():
        """FR-12: ejecuta a mano lo mismo que hace el evento diario de MySQL."""
        before = db.session.scalar(
            db.select(func.count()).select_from(Invoice)
            .where(Invoice.payment_status == "Overdue"))
        db.session.execute(text("CALL sp_mark_overdue_invoices()"))
        db.session.commit()
        after = db.session.scalar(
            db.select(func.count()).select_from(Invoice)
            .where(Invoice.payment_status == "Overdue"))
        return jsonify({"marked_overdue": after - before, "total_overdue": after})

    # ---------------- Reportes ----------------
    def period():
        """Lee date_from y date_to de la URL (obligatorios en los reportes)."""
        if not request.args.get("date_from") or not request.args.get("date_to"):
            raise ApiError("Indique date_from y date_to (AAAA-MM-DD).")
        return (to_date(request.args["date_from"], "date_from"),
                to_date(request.args["date_to"], "date_to"))

    @app.get("/reports/expenses")
    def report_expenses():
        """FR-05: gasto total e IVA de un período."""
        date_from, date_to = period()
        row = db.session.execute(
            db.select(
                func.count(Invoice.invoice_id),
                func.coalesce(func.sum(Invoice.subtotal), 0),
                func.coalesce(func.sum(Invoice.vat), 0),
                func.coalesce(func.sum(Invoice.total_amount), 0),
            ).where(Invoice.issue_date.between(date_from, date_to))
        ).one()
        return jsonify({
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "invoice_count": row[0],
            "total_subtotal": money(row[1]),
            "total_vat": money(row[2]),
            "total_expense": money(row[3]),
        })

    @app.get("/reports/supplier-balance")
    def report_supplier_balance():
        """FR-13: saldo pendiente por proveedor (usa la vista vw_supplier_balance)."""
        sql = "SELECT * FROM vw_supplier_balance"
        params = {}
        if request.args.get("supplier_id"):
            sql += " WHERE supplier_id = :supplier_id"
            params["supplier_id"] = request.args["supplier_id"]
        rows = db.session.execute(text(sql + " ORDER BY company_name"), params).mappings()
        return jsonify([
            {
                "supplier_id": r["supplier_id"],
                "company_name": r["company_name"],
                "tax_id": r["tax_id"],
                "total_invoiced": money(r["total_invoiced"]),
                "total_paid": money(r["total_paid"]),
                "pending_balance": money(r["pending_balance"]),
            }
            for r in rows
        ])

    @app.get("/reports/department-expenses")
    def report_department_expenses():
        """FR-14: gasto e IVA por departamento (usa la vista vw_department_expense)."""
        date_from, date_to = period()
        rows = db.session.execute(text(
            "SELECT department_id, department_name, SUM(invoice_count) AS invoice_count,"
            "       SUM(subtotal) AS subtotal, SUM(vat) AS vat,"
            "       SUM(total_amount) AS total_amount "
            "FROM vw_department_expense "
            "WHERE issue_date BETWEEN :date_from AND :date_to "
            "GROUP BY department_id, department_name ORDER BY department_name"
        ), {"date_from": date_from, "date_to": date_to}).mappings()
        return jsonify([
            {
                "department_id": r["department_id"],
                "department_name": r["department_name"],
                "invoice_count": int(r["invoice_count"]),
                "subtotal": money(r["subtotal"]),
                "vat": money(r["vat"]),
                "total_amount": money(r["total_amount"]),
            }
            for r in rows
        ])

    @app.get("/reports/summary")
    def report_summary():
        """Resumen general para la pantalla inicial de la interfaz gráfica."""
        by_status = {
            status: {"invoice_count": count, "total_amount": money(total)}
            for status, count, total in db.session.execute(
                db.select(Invoice.payment_status, func.count(),
                          func.coalesce(func.sum(Invoice.total_amount), 0))
                .group_by(Invoice.payment_status))
        }
        invoiced = db.session.scalar(db.select(func.coalesce(func.sum(Invoice.total_amount), 0)))
        paid = db.session.scalar(db.select(func.coalesce(func.sum(Payment.amount_paid), 0)))

        def count(model):
            return db.session.scalar(db.select(func.count()).select_from(model))

        return jsonify({
            "suppliers": count(Supplier),
            "products": count(Product),
            "categories": count(Category),
            "invoices": count(Invoice),
            "payments": count(Payment),
            "invoices_by_status": by_status,
            "total_invoiced": money(invoiced),
            "total_paid": money(paid),
            "pending_balance": money(invoiced - paid),
        })

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
