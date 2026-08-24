SET search_path TO app, public;
CREATE TABLE media_asset (
  media_id BIGSERIAL PRIMARY KEY,
  style_id INT REFERENCES style(style_id) ON DELETE CASCADE,
  jewel_code_id INT REFERENCES jewel_code(jewel_code_id) ON DELETE CASCADE,
  kind media_kind NOT NULL, storage_url TEXT NOT NULL, thumb_url TEXT,
  view_angle TEXT, rank_order INT NOT NULL DEFAULT 100,
  is_catalogue_default BOOLEAN NOT NULL DEFAULT FALSE,
  width_px INT, height_px INT, file_size_kb INT,
  uploaded_by INT REFERENCES app_user(user_id),
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (style_id IS NOT NULL OR jewel_code_id IS NOT NULL));
CREATE INDEX idx_media_jc ON media_asset(jewel_code_id, rank_order);
CREATE INDEX idx_media_st ON media_asset(style_id, rank_order);
CREATE TABLE catalogue_template (
  template_id SERIAL PRIMARY KEY, name TEXT NOT NULL, layout TEXT NOT NULL DEFAULT 'GRID_2x2',
  show_sale_price BOOLEAN NOT NULL DEFAULT TRUE,
  show_cost_price BOOLEAN NOT NULL DEFAULT FALSE,
  show_material_breakup BOOLEAN NOT NULL DEFAULT FALSE,
  show_dimensions BOOLEAN NOT NULL DEFAULT TRUE,
  show_gross_weight BOOLEAN NOT NULL DEFAULT TRUE,
  show_location BOOLEAN NOT NULL DEFAULT FALSE,
  show_in_stock_flag BOOLEAN NOT NULL DEFAULT TRUE,
  created_by INT REFERENCES app_user(user_id));
CREATE TABLE catalogue (
  catalogue_id SERIAL PRIMARY KEY, name TEXT NOT NULL,
  template_id INT NOT NULL REFERENCES catalogue_template(template_id),
  generated_for TEXT, generated_by INT REFERENCES app_user(user_id),
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(), output_url TEXT);
CREATE TABLE catalogue_item (
  catalogue_id INT NOT NULL REFERENCES catalogue(catalogue_id) ON DELETE CASCADE,
  jewel_code_id INT NOT NULL REFERENCES jewel_code(jewel_code_id),
  sort_order INT NOT NULL DEFAULT 0,
  media_id BIGINT REFERENCES media_asset(media_id),
  PRIMARY KEY (catalogue_id, jewel_code_id));
CREATE TABLE job_card (
  job_card_id BIGSERIAL PRIMARY KEY, job_no TEXT NOT NULL UNIQUE,
  style_id INT NOT NULL REFERENCES style(style_id),
  jewel_code_id INT REFERENCES jewel_code(jewel_code_id),
  vendor_id INT REFERENCES vendor(vendor_id),
  issued_on DATE NOT NULL, expected_on DATE, received_on DATE,
  status TEXT NOT NULL DEFAULT 'OPEN'
         CHECK (status IN ('OPEN','WITH_VENDOR','RECEIVED','CANCELLED')),
  estimated_cost NUMERIC(14,2), actual_cost NUMERIC(14,2),
  digital_copy_url TEXT, created_by INT REFERENCES app_user(user_id),
  tat_days INT GENERATED ALWAYS AS (received_on - issued_on) STORED);
CREATE TABLE material_inventory (
  material_id INT NOT NULL REFERENCES material(material_id),
  location_id INT NOT NULL REFERENCES location(location_id),
  size_band TEXT NOT NULL DEFAULT '',
  qty_value NUMERIC(14,4) NOT NULL DEFAULT 0, qty_uom uom NOT NULL, pcs INT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (material_id, location_id, size_band));
CREATE TABLE activity_log (
  log_id BIGSERIAL PRIMARY KEY, table_name TEXT NOT NULL, record_pk TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('INSERT','UPDATE','DELETE','VIEW_COST','EXPORT','LOGIN','MELT','REPAIR')),
  user_id INT REFERENCES app_user(user_id),
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  old_values JSONB, new_values JSONB);
CREATE INDEX idx_log_rec ON activity_log(table_name, record_pk, changed_at DESC);
CREATE OR REPLACE VIEW vw_weight_reconciliation AS
SELECT jc.jewel_code, b.version_no, jc.measured_gross_wt_gm, b.bom_weight_gm,
       ROUND(jc.measured_gross_wt_gm - b.bom_weight_gm, 3) AS diff_gm,
       ABS(jc.measured_gross_wt_gm - b.bom_weight_gm) > setting_num('gross_wt_tolerance_gm',0.05)
         AS out_of_tolerance
FROM jewel_code jc JOIN bom_version b
  ON b.jewel_code_id=jc.jewel_code_id AND b.is_current
WHERE jc.measured_gross_wt_gm IS NOT NULL;
CREATE OR REPLACE VIEW vw_should_make AS
SELECT s.style_id, s.style_code, s.name, s.nos_min_qty,
       COUNT(jc.jewel_code_id) FILTER (WHERE jc.stock_state='IN_STOCK') AS live_pieces,
       s.nos_min_qty - COUNT(jc.jewel_code_id) FILTER (WHERE jc.stock_state='IN_STOCK') AS shortfall
FROM style s LEFT JOIN jewel_code jc ON jc.style_id=s.style_id
WHERE s.is_active
GROUP BY s.style_id, s.style_code, s.name, s.nos_min_qty
HAVING s.nos_min_qty > COUNT(jc.jewel_code_id) FILTER (WHERE jc.stock_state='IN_STOCK');
CREATE OR REPLACE VIEW vw_bom_history AS
SELECT jc.jewel_code, b.version_no, b.reason, b.note, b.is_current,
       b.bom_weight_gm, b.total_cost_price, b.total_sale_price,
       rj.job_no AS repair_job, b.created_at
FROM bom_version b
JOIN jewel_code jc USING (jewel_code_id)
LEFT JOIN repair_job rj ON rj.repair_job_id=b.repair_job_id
ORDER BY jc.jewel_code, b.version_no;;
