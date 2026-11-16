"""Modelos de SQLAlchemy: una clase por cada tabla de la base de datos.

Las tablas NO se crean desde aquí; ya las crea Docker con db/01_schema.sql.
Estas clases solo le dicen a Python cómo se llama cada tabla y cada columna.
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def money(value):
    """Convierte un DECIMAL de MySQL a número normal para poder enviarlo en JSON."""
    return float(value) if value is not None else None


class Supplier(db.Model):
    __tablename__ = "supplier"
    supplier_id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False)
    tax_id = db.Column(db.String(20), nullable=False, unique=True)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))

    def to_dict(self):
        return {
            "supplier_id": self.supplier_id,
            "company_name": self.company_name,
            "tax_id": self.tax_id,
            "phone": self.phone,
            "email": self.email,
        }


class AppUser(db.Model):
    __tablename__ = "app_user"
    app_user_id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    role = db.Column(db.String(20), nullable=False)

    def to_dict(self):
        return {
            "app_user_id": self.app_user_id,
            "full_name": self.full_name,
            "email": self.email,
            "role": self.role,
        }


class Department(db.Model):
    __tablename__ = "department"
    department_id = db.Column(db.Integer, primary_key=True)
    department_name = db.Column(db.String(80), nullable=False, unique=True)

    def to_dict(self):
        return {
            "department_id": self.department_id,
            "department_name": self.department_name,
        }


class Category(db.Model):
    __tablename__ = "category"
    category_id = db.Column(db.Integer, primary_key=True)
    category_name = db.Column(db.String(60), nullable=False, unique=True)

    def to_dict(self):
        return {
            "category_id": self.category_id,
            "category_name": self.category_name,
        }


class TaxRate(db.Model):
    __tablename__ = "tax_rate"
    tax_rate_id = db.Column(db.Integer, primary_key=True)
    rate_name = db.Column(db.String(30), nullable=False, unique=True)
    rate_percent = db.Column(db.Numeric(5, 2), nullable=False)

    def to_dict(self):
        return {
            "tax_rate_id": self.tax_rate_id,
            "rate_name": self.rate_name,
            "rate_percent": money(self.rate_percent),
        }


class PaymentMethod(db.Model):
    __tablename__ = "payment_method"
    payment_method_id = db.Column(db.Integer, primary_key=True)
    method_name = db.Column(db.String(30), nullable=False, unique=True)

    def to_dict(self):
        return {
            "payment_method_id": self.payment_method_id,
            "method_name": self.method_name,
        }


class Product(db.Model):
    __tablename__ = "product"
    product_id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(150), nullable=False, unique=True)
    category_id = db.Column(
        db.Integer, db.ForeignKey("category.category_id"), nullable=False
    )
    unit_of_measure = db.Column(db.String(20), nullable=False)

    category = db.relationship("Category")

    def to_dict(self):
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "category_id": self.category_id,
            "category_name": self.category.category_name if self.category else None,
            "unit_of_measure": self.unit_of_measure,
        }


class Invoice(db.Model):
    __tablename__ = "invoice"
    invoice_id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(
        db.Integer, db.ForeignKey("supplier.supplier_id"), nullable=False
    )
    app_user_id = db.Column(
        db.Integer, db.ForeignKey("app_user.app_user_id"), nullable=False
    )
    department_id = db.Column(
        db.Integer, db.ForeignKey("department.department_id"), nullable=False
    )
    invoice_number = db.Column(db.String(30), nullable=False)
    issue_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    subtotal = db.Column(db.Numeric(10, 2), nullable=False)
    vat = db.Column(db.Numeric(10, 2), nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_status = db.Column(db.String(20), nullable=False, default="Pending")

    supplier = db.relationship("Supplier")
    app_user = db.relationship("AppUser")
    department = db.relationship("Department")
    # Una factura tiene muchas líneas de detalle y muchos pagos (1:N)
    details = db.relationship(
        "InvoiceDetail", back_populates="invoice", cascade="all, delete-orphan"
    )
    payments = db.relationship("Payment", back_populates="invoice")

    def total_paid(self):
        return sum((p.amount_paid for p in self.payments), 0)

    def to_dict(self, full=False):
        """full=True agrega las líneas de detalle y los pagos."""
        data = {
            "invoice_id": self.invoice_id,
            "invoice_number": self.invoice_number,
            "supplier_id": self.supplier_id,
            "supplier_name": self.supplier.company_name if self.supplier else None,
            "department_id": self.department_id,
            "department_name": (
                self.department.department_name if self.department else None
            ),
            "app_user_id": self.app_user_id,
            "issue_date": self.issue_date.isoformat(),
            "due_date": self.due_date.isoformat(),
            "subtotal": money(self.subtotal),
            "vat": money(self.vat),
            "total_amount": money(self.total_amount),
            "payment_status": self.payment_status,
        }
        if full:
            paid = self.total_paid()
            data["total_paid"] = money(paid)
            data["pending_balance"] = money(self.total_amount - paid)
            data["details"] = [d.to_dict() for d in self.details]
            data["payments"] = [p.to_dict() for p in self.payments]
        return data


class InvoiceDetail(db.Model):
    __tablename__ = "invoice_detail"
    detail_id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoice.invoice_id"), nullable=False
    )
    product_id = db.Column(
        db.Integer, db.ForeignKey("product.product_id"), nullable=False
    )
    tax_rate_id = db.Column(
        db.Integer, db.ForeignKey("tax_rate.tax_rate_id"), nullable=False
    )
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    line_total = db.Column(db.Numeric(10, 2), nullable=False)

    invoice = db.relationship("Invoice", back_populates="details")
    product = db.relationship("Product")
    tax_rate = db.relationship("TaxRate")

    def to_dict(self):
        return {
            "detail_id": self.detail_id,
            "invoice_id": self.invoice_id,
            "product_id": self.product_id,
            "product_name": self.product.product_name if self.product else None,
            "tax_rate_id": self.tax_rate_id,
            "rate_percent": money(self.tax_rate.rate_percent) if self.tax_rate else None,
            "quantity": money(self.quantity),
            "unit_price": money(self.unit_price),
            "line_total": money(self.line_total),
        }


class Payment(db.Model):
    __tablename__ = "payment"
    payment_id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoice.invoice_id"), nullable=False
    )
    app_user_id = db.Column(
        db.Integer, db.ForeignKey("app_user.app_user_id"), nullable=False
    )
    payment_date = db.Column(db.Date, nullable=False)
    amount_paid = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method_id = db.Column(
        db.Integer, db.ForeignKey("payment_method.payment_method_id"), nullable=False
    )

    invoice = db.relationship("Invoice", back_populates="payments")
    app_user = db.relationship("AppUser")
    payment_method = db.relationship("PaymentMethod")

    def to_dict(self):
        return {
            "payment_id": self.payment_id,
            "invoice_id": self.invoice_id,
            "app_user_id": self.app_user_id,
            "payment_date": self.payment_date.isoformat(),
            "amount_paid": money(self.amount_paid),
            "payment_method_id": self.payment_method_id,
            "method_name": (
                self.payment_method.method_name if self.payment_method else None
            ),
        }
