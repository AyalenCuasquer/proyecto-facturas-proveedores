-- =====================================================================
--  02_views_events.sql  ->  Vistas, procedimiento y evento programado
-- =====================================================================

-- ---------------------------------------------------------------------
-- FR-13  vw_supplier_balance
-- Una fila por proveedor: total facturado, total pagado y saldo pendiente.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_supplier_balance AS
SELECT
    s.supplier_id,
    s.company_name,
    s.tax_id,
    COALESCE(f.total_invoiced, 0)                            AS total_invoiced,
    COALESCE(p.total_paid, 0)                                AS total_paid,
    COALESCE(f.total_invoiced, 0) - COALESCE(p.total_paid, 0) AS pending_balance
FROM supplier s
LEFT JOIN (
    SELECT supplier_id, SUM(total_amount) AS total_invoiced
    FROM invoice
    GROUP BY supplier_id
) f ON f.supplier_id = s.supplier_id
LEFT JOIN (
    SELECT i.supplier_id, SUM(pa.amount_paid) AS total_paid
    FROM payment pa
    JOIN invoice i ON i.invoice_id = pa.invoice_id
    GROUP BY i.supplier_id
) p ON p.supplier_id = s.supplier_id;

-- ---------------------------------------------------------------------
-- FR-14  vw_department_expense
-- Gasto por departamento y fecha de emisión. Se deja la fecha en la vista
-- para poder filtrar un período:
--   SELECT department_name, SUM(subtotal), SUM(vat), SUM(total_amount)
--   FROM vw_department_expense
--   WHERE issue_date BETWEEN '2026-10-01' AND '2026-10-31'
--   GROUP BY department_name;
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_department_expense AS
SELECT
    d.department_id,
    d.department_name,
    i.issue_date,
    COUNT(*)            AS invoice_count,
    SUM(i.subtotal)     AS subtotal,
    SUM(i.vat)          AS vat,
    SUM(i.total_amount) AS total_amount
FROM department d
JOIN invoice i ON i.department_id = d.department_id
GROUP BY d.department_id, d.department_name, i.issue_date;

-- ---------------------------------------------------------------------
-- FR-12 / NFR-06  Marcado automático de facturas vencidas
-- El procedimiento hace el trabajo; el evento lo llama todos los días.
-- (Tener el procedimiento aparte permite ejecutarlo a mano para probar:
--    CALL sp_mark_overdue_invoices(); )
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_mark_overdue_invoices;

CREATE PROCEDURE sp_mark_overdue_invoices()
    UPDATE invoice
    SET payment_status = 'Overdue'
    WHERE payment_status = 'Pending'
      AND due_date < CURDATE();

DROP EVENT IF EXISTS evt_mark_overdue_invoices;

CREATE EVENT evt_mark_overdue_invoices
    ON SCHEDULE EVERY 1 DAY
    STARTS (CURRENT_DATE + INTERVAL 1 DAY)      -- cada día a las 00:00
    ON COMPLETION PRESERVE
    COMMENT 'Marca como Overdue las facturas Pending cuya due_date ya pasó'
    DO CALL sp_mark_overdue_invoices();
