-- =====================================================================
--  Sistema de Gestión de Facturas de Proveedores
--  01_schema.sql  ->  Tablas, claves primarias, claves foráneas,
--                     restricciones UNIQUE y CHECK, e índices.
--  Nomenclatura (Anexo B): pk_, fk_, uq_, ck_, idx_
--  Este archivo se ejecuta solo la primera vez que arranca el contenedor.
-- =====================================================================

-- ---------- Tablas "catálogo" (no dependen de ninguna otra) ----------

CREATE TABLE supplier (
    supplier_id   INT          NOT NULL AUTO_INCREMENT,
    company_name  VARCHAR(150) NOT NULL,
    tax_id        VARCHAR(20)  NOT NULL,          -- RUC o RIMPE
    phone         VARCHAR(20)  NULL,
    email         VARCHAR(120) NULL,
    CONSTRAINT pk_supplier PRIMARY KEY (supplier_id),
    CONSTRAINT uq_supplier_tax_id UNIQUE (tax_id)
);

CREATE TABLE app_user (
    app_user_id  INT          NOT NULL AUTO_INCREMENT,
    full_name    VARCHAR(120) NOT NULL,
    email        VARCHAR(120) NOT NULL,
    role         VARCHAR(20)  NOT NULL,
    CONSTRAINT pk_app_user PRIMARY KEY (app_user_id),
    CONSTRAINT uq_app_user_email UNIQUE (email),
    CONSTRAINT ck_app_user_role CHECK (role IN ('Admin', 'Accountant', 'Viewer'))
);

CREATE TABLE department (
    department_id    INT         NOT NULL AUTO_INCREMENT,
    department_name  VARCHAR(80) NOT NULL,
    CONSTRAINT pk_department PRIMARY KEY (department_id),
    CONSTRAINT uq_department_department_name UNIQUE (department_name)
);

CREATE TABLE category (
    category_id    INT         NOT NULL AUTO_INCREMENT,
    category_name  VARCHAR(60) NOT NULL,
    CONSTRAINT pk_category PRIMARY KEY (category_id),
    CONSTRAINT uq_category_category_name UNIQUE (category_name)
);

CREATE TABLE tax_rate (
    tax_rate_id   INT          NOT NULL AUTO_INCREMENT,
    rate_name     VARCHAR(30)  NOT NULL,
    rate_percent  DECIMAL(5,2) NOT NULL,
    CONSTRAINT pk_tax_rate PRIMARY KEY (tax_rate_id),
    CONSTRAINT uq_tax_rate_rate_name UNIQUE (rate_name),
    CONSTRAINT ck_tax_rate_percent_range CHECK (rate_percent BETWEEN 0 AND 100)
);

CREATE TABLE payment_method (
    payment_method_id  INT         NOT NULL AUTO_INCREMENT,
    method_name        VARCHAR(30) NOT NULL,
    CONSTRAINT pk_payment_method PRIMARY KEY (payment_method_id),
    CONSTRAINT uq_payment_method_method_name UNIQUE (method_name)
);

-- ---------- Producto (depende de category) ----------

CREATE TABLE product (
    product_id       INT          NOT NULL AUTO_INCREMENT,
    product_name     VARCHAR(150) NOT NULL,
    category_id      INT          NOT NULL,
    unit_of_measure  VARCHAR(20)  NOT NULL,
    CONSTRAINT pk_product PRIMARY KEY (product_id),
    CONSTRAINT uq_product_product_name UNIQUE (product_name),
    CONSTRAINT fk_product_category FOREIGN KEY (category_id)
        REFERENCES category (category_id)
);

-- ---------- Factura (depende de supplier, app_user, department) ----------

CREATE TABLE invoice (
    invoice_id      INT           NOT NULL AUTO_INCREMENT,
    supplier_id     INT           NOT NULL,
    app_user_id     INT           NOT NULL,
    department_id   INT           NOT NULL,
    invoice_number  VARCHAR(30)   NOT NULL,
    issue_date      DATE          NOT NULL,
    due_date        DATE          NOT NULL,
    subtotal        DECIMAL(10,2) NOT NULL,
    vat             DECIMAL(10,2) NOT NULL,
    total_amount    DECIMAL(10,2) NOT NULL,
    payment_status  VARCHAR(20)   NOT NULL DEFAULT 'Pending',
    CONSTRAINT pk_invoice PRIMARY KEY (invoice_id),
    -- FR-03: el mismo proveedor no puede repetir un número de factura
    CONSTRAINT uq_invoice_invoice_number UNIQUE (supplier_id, invoice_number),
    CONSTRAINT fk_invoice_supplier FOREIGN KEY (supplier_id)
        REFERENCES supplier (supplier_id),
    CONSTRAINT fk_invoice_app_user FOREIGN KEY (app_user_id)
        REFERENCES app_user (app_user_id),
    CONSTRAINT fk_invoice_department FOREIGN KEY (department_id)
        REFERENCES department (department_id),
    CONSTRAINT ck_invoice_total_equals_subtotal_plus_vat
        CHECK (total_amount = subtotal + vat),
    CONSTRAINT ck_invoice_amounts_non_negative
        CHECK (subtotal >= 0 AND vat >= 0),
    CONSTRAINT ck_invoice_payment_status
        CHECK (payment_status IN ('Pending', 'Paid', 'Overdue')),
    CONSTRAINT ck_invoice_due_date_after_issue
        CHECK (due_date >= issue_date)
);

-- Índices para que las búsquedas (FR-04) y reportes sean rápidos (NFR-03)
CREATE INDEX idx_invoice_issue_date     ON invoice (issue_date);
CREATE INDEX idx_invoice_payment_status ON invoice (payment_status);
CREATE INDEX idx_invoice_due_date       ON invoice (due_date);

-- ---------- Detalle de factura (depende de invoice, product, tax_rate) ----------

CREATE TABLE invoice_detail (
    detail_id    INT           NOT NULL AUTO_INCREMENT,
    invoice_id   INT           NOT NULL,
    product_id   INT           NOT NULL,
    tax_rate_id  INT           NOT NULL,
    quantity     DECIMAL(10,2) NOT NULL,
    unit_price   DECIMAL(10,2) NOT NULL,
    line_total   DECIMAL(10,2) NOT NULL,          -- antes de impuestos
    CONSTRAINT pk_invoice_detail PRIMARY KEY (detail_id),
    CONSTRAINT fk_invoice_detail_invoice FOREIGN KEY (invoice_id)
        REFERENCES invoice (invoice_id) ON DELETE CASCADE,
    CONSTRAINT fk_invoice_detail_product FOREIGN KEY (product_id)
        REFERENCES product (product_id),
    CONSTRAINT fk_invoice_detail_tax_rate FOREIGN KEY (tax_rate_id)
        REFERENCES tax_rate (tax_rate_id),
    CONSTRAINT ck_invoice_detail_quantity_positive
        CHECK (quantity > 0),
    CONSTRAINT ck_invoice_detail_unit_price_non_negative
        CHECK (unit_price >= 0),
    -- Se redondea a 2 decimales porque line_total solo guarda 2 decimales
    CONSTRAINT ck_invoice_detail_line_total
        CHECK (line_total = ROUND(quantity * unit_price, 2))
);

-- ---------- Pago (depende de invoice, app_user, payment_method) ----------

CREATE TABLE payment (
    payment_id         INT           NOT NULL AUTO_INCREMENT,
    invoice_id         INT           NOT NULL,
    app_user_id        INT           NOT NULL,
    payment_date       DATE          NOT NULL,
    amount_paid        DECIMAL(10,2) NOT NULL,
    payment_method_id  INT           NOT NULL,
    CONSTRAINT pk_payment PRIMARY KEY (payment_id),
    CONSTRAINT fk_payment_invoice FOREIGN KEY (invoice_id)
        REFERENCES invoice (invoice_id),
    CONSTRAINT fk_payment_app_user FOREIGN KEY (app_user_id)
        REFERENCES app_user (app_user_id),
    CONSTRAINT fk_payment_payment_method FOREIGN KEY (payment_method_id)
        REFERENCES payment_method (payment_method_id),
    CONSTRAINT ck_payment_amount_positive CHECK (amount_paid > 0)
);

CREATE INDEX idx_payment_payment_date ON payment (payment_date);
