# Sistema de Gestión de Facturas de Proveedores

Base de datos MySQL 8 en Docker + API en Python (Flask + SQLAlchemy) + interfaz gráfica web.

```
proyecto-facturas/
├── docker-compose.yml        contenedor mysql-facturas (puerto 3309, root / 1234, base invoice_db)
├── db/
│   ├── 01_schema.sql         10 tablas, PK, FK, UNIQUE, CHECK, índices
│   ├── 02_views_events.sql   vw_supplier_balance, vw_department_expense, evt_mark_overdue_invoices
│   ├── 03_seed.sql           proveedores, facturas y pagos reales (generado desde el Excel)
│   └── 04_products.sql       catálogo real de productos (generado desde el inventario)
├── api/
│   ├── app.py                rutas de la API (y sirve la interfaz gráfica en /app)
│   ├── models.py             una clase por tabla
│   ├── config.py             datos de conexión
│   └── requirements.txt
├── gui/                      interfaz gráfica (HTML + CSS + JavaScript, sin librerías)
│   ├── index.html
│   ├── styles.css
│   └── app.js                cada pantalla llama a la API con fetch()
├── tests/test_casos.py       casos de prueba TC-01 a TC-11
├── datos/
│   ├── CONTROL_PROVEEDORES_BASE.xlsx      Excel original (proveedores, facturas, pagos)
│   ├── Inventario_Productos_CARMAX.pdf    reporte original del inventario
│   └── inventario_productos.csv           el inventario ya extraído del PDF
└── tools/
    ├── generar_seed.py       convierte el Excel en db/03_seed.sql
    ├── extraer_inventario.py convierte el PDF del inventario en el CSV
    └── generar_productos.py  convierte el CSV en db/04_products.sql
```

## 1. Encender la base de datos (cmd o PowerShell, dentro de esta carpeta)

```
docker compose up -d
docker ps
```

Debe aparecer `mysql-facturas` con STATUS `Up`. La primera vez Docker ejecuta
solo los cuatro archivos de `db/`. Para ver las tablas:

```
docker exec -it mysql-facturas mysql -uroot -p1234 invoice_db -e "SHOW FULL TABLES;"
```

Para borrar todo y crear la base de nuevo: `docker compose down -v` y luego `docker compose up -d`.

## 2. Instalar las librerías (PowerShell, una sola vez)

```
conda activate apidb
pip install -r api\requirements.txt
```

## 3. Ejecutar los casos de prueba

```
python -m pytest tests -v
```

Deben salir 11 `PASSED`. Las pruebas usan una base aparte (`invoice_db_test`),
no tocan los datos reales.

## 4. Encender la API y la interfaz gráfica

```
cd api
python app.py
```

- Interfaz gráfica: http://127.0.0.1:5000/app
- Lista de rutas de la API: http://127.0.0.1:5000/

La interfaz tiene cinco pantallas: Resumen, Proveedores (crear, editar, eliminar y buscar),
Facturas (filtros, detalle y registro de pagos), Productos (búsqueda por nombre y categoría)
y Reportes (saldo por proveedor, gasto e IVA por período, gasto por departamento).
Todo lo que muestra lo pide a la API; no se conecta directo a la base de datos.

Para probar la API sin la interfaz (en **cmd**, no PowerShell):

```
curl http://127.0.0.1:5000/suppliers
curl "http://127.0.0.1:5000/invoices?status=Pending"
curl "http://127.0.0.1:5000/reports/expenses?date_from=2026-10-01&date_to=2026-10-31"
curl http://127.0.0.1:5000/reports/supplier-balance
curl -X POST http://127.0.0.1:5000/suppliers -H "Content-Type: application/json" -d "{\"company_name\": \"Proveedor Demo\", \"tax_id\": \"1790099999001\"}"
```

## De dónde salen los datos

`db/03_seed.sql` se genera con `python tools/generar_seed.py` (necesita `pip install openpyxl`)
a partir de `datos/CONTROL_PROVEEDORES_BASE.xlsx`: 34 proveedores, 122 facturas,
122 líneas de detalle y 108 pagos. No se usan las hojas CHEQUES ni CONSULTA_CXP.

| Hoja del Excel | Tabla |
|---|---|
| Proveedores | `supplier` (RUC, nombre, teléfono) |
| Fechas | `invoice` (subtotal, IVA, total) e `invoice_detail` (una línea por factura con la tasa IVA 15 %) |
| FACTURAS_CXP | `invoice.due_date` y `payment` (cada plazo marcado con "P" es un pago) |

Lo que el Excel no trae y se completó: todas las facturas van al departamento `Purchasing`,
las registra el usuario `Contabilidad CARMAX`, los pagos son `Bank transfer`, y el detalle usa
un producto general ("Compra de repuestos automotrices").

El sistema maneja una sola tasa de impuesto (IVA 15 %). Los montos de cada factura (subtotal,
IVA y total) son los de la factura real del Excel.

`db/04_products.sql` se genera con `python tools/generar_productos.py` a partir de
`datos/inventario_productos.csv` (reporte "Inventario de Productos" del 30-oct-2026):
4 629 productos en 14 categorías. La categoría se asigna por la primera palabra del nombre
(FILTRO → Filtros, PASTILLA → Frenos y embrague, …) y lo que no coincide va a "Otros repuestos".
De ese reporte solo se usa el nombre del producto; la cantidad y el costo no se cargan porque
el sistema gestiona facturas de proveedores, no inventario.

Si cambia el Excel o el inventario: `python tools/generar_seed.py` o `python tools/generar_productos.py`, luego `docker compose down -v` y `docker compose up -d`.

## Requisito → dónde está

| Requisito | Dónde |
|---|---|
| FR-01 proveedores | `POST /suppliers`, `uq_supplier_tax_id` |
| FR-02, FR-07 facturas y detalles | `POST /invoices`, `POST /invoices/<id>/details` |
| FR-03 número único por proveedor | `uq_invoice_invoice_number` |
| FR-04 búsquedas | `GET /invoices?supplier_id=&status=&date_from=&date_to=` |
| FR-05 reporte del período | `GET /reports/expenses` |
| FR-06 catálogo | `/products?q=&category_id=&limit=&offset=`, `/categories` |
| FR-08, FR-09 pagos | `POST /invoices/<id>/payments` (la API valida la suma y cambia a `Paid`) |
| FR-10, FR-11 usuario y departamento | columnas NOT NULL + FK en `invoice` y `payment` |
| FR-12 vencidas | `evt_mark_overdue_invoices` (diario) y `POST /invoices/mark-overdue` |
| FR-13 saldo por proveedor | `vw_supplier_balance`, `GET /reports/supplier-balance` |
| FR-14 gasto por departamento | `vw_department_expense`, `GET /reports/department-expenses` |
