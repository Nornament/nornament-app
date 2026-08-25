SET search_path TO app, public;
CREATE OR REPLACE FUNCTION line_weight_gm(p_qty NUMERIC, p_uom uom) RETURNS NUMERIC
LANGUAGE sql IMMUTABLE AS $$
  SELECT COALESCE(p_qty,0)*(SELECT grams_per_unit FROM uom_conversion WHERE unit=p_uom); $$;
CREATE OR REPLACE FUNCTION trg_check_line_uom() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_class material_class;
BEGIN
  SELECT mat_class INTO v_class FROM material WHERE material_id=NEW.material_id;
  IF v_class='METAL' AND NEW.qty_uom<>'GM' THEN
    RAISE EXCEPTION 'Metal line % must be GM, got %', NEW.line_no, NEW.qty_uom; END IF;
  IF v_class IN ('DIAMOND','POLKI') AND NEW.qty_uom NOT IN ('CT','PCS') THEN
    RAISE EXCEPTION 'Diamond/Polki line % must be CT or PCS, got %', NEW.line_no, NEW.qty_uom; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER check_line_uom BEFORE INSERT OR UPDATE ON jewel_material_line
FOR EACH ROW EXECUTE FUNCTION trg_check_line_uom();
CREATE OR REPLACE FUNCTION recost_jewel(p_jc INT, p_version INT DEFAULT NULL, p_user INT DEFAULT NULL)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
  v INT := COALESCE(p_version,(SELECT current_bom_version FROM jewel_code WHERE jewel_code_id=p_jc));
  v_metal NUMERIC;
  ldp INT := setting_int('line_rounding_dp',0);
  tdp INT := setting_int('total_rounding_dp',0);
BEGIN
  SELECT COALESCE(SUM(line_weight_gm(l.qty_value,l.qty_uom)),0) INTO v_metal
  FROM jewel_material_line l JOIN material m USING (material_id)
  WHERE l.jewel_code_id=p_jc AND l.version_no=v AND m.mat_class='METAL';
  UPDATE jewel_material_line l SET qty_value=v_metal, qty_uom='GM',
      cost_amount=ROUND(COALESCE(l.cost_rate,0)*v_metal,ldp),
      sale_amount=ROUND(COALESCE(l.sale_rate,0)*v_metal,ldp)
    WHERE l.jewel_code_id=p_jc AND l.version_no=v AND l.basis='BY_NET_METAL_WT';
  UPDATE jewel_material_line l
     SET cost_amount=ROUND(COALESCE(l.cost_rate,0)*COALESCE(l.qty_value,0),ldp),
         sale_amount=ROUND(COALESCE(l.sale_rate,0)*COALESCE(l.qty_value,0),ldp)
    WHERE l.jewel_code_id=p_jc AND l.version_no=v AND l.basis='BY_QTY';
  UPDATE jewel_material_line l
     SET cost_amount=ROUND(COALESCE(l.cost_rate,0)*COALESCE(l.pcs,0),ldp),
         sale_amount=ROUND(COALESCE(l.sale_rate,0)*COALESCE(l.pcs,0),ldp)
    WHERE l.jewel_code_id=p_jc AND l.version_no=v AND l.basis='BY_PIECE';
  UPDATE bom_version b SET
    net_metal_wt_gm = v_metal,
    bom_weight_gm = (SELECT COALESCE(SUM(line_weight_gm(l.qty_value,l.qty_uom)),0)
                       FROM jewel_material_line l JOIN material m USING (material_id)
                      WHERE l.jewel_code_id=p_jc AND l.version_no=v AND m.mat_class<>'LABOUR'),
    total_cost_price = ROUND((SELECT COALESCE(SUM(cost_amount),0) FROM jewel_material_line
                               WHERE jewel_code_id=p_jc AND version_no=v),tdp),
    total_sale_price = ROUND((SELECT COALESCE(SUM(sale_amount),0) FROM jewel_material_line
                               WHERE jewel_code_id=p_jc AND version_no=v),tdp),
    making_value = ROUND((SELECT COALESCE(SUM(l.sale_amount),0) FROM jewel_material_line l
                            JOIN material m USING (material_id)
                           WHERE l.jewel_code_id=p_jc AND l.version_no=v AND m.mat_class='LABOUR'),tdp),
    goods_value  = ROUND((SELECT COALESCE(SUM(l.sale_amount),0) FROM jewel_material_line l
                            JOIN material m USING (material_id)
                           WHERE l.jewel_code_id=p_jc AND l.version_no=v AND m.mat_class<>'LABOUR'),tdp)
  WHERE b.jewel_code_id=p_jc AND b.version_no=v;
END $$;
CREATE TABLE stock_movement (
  movement_id BIGSERIAL PRIMARY KEY,
  jewel_code_id INT NOT NULL REFERENCES jewel_code(jewel_code_id),
  move_type movement_type NOT NULL,
  from_location_id INT REFERENCES location(location_id),
  to_location_id   INT REFERENCES location(location_id),
  resulting_state stock_state NOT NULL,
  moved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  reference_no TEXT,
  party_name TEXT,
  reason TEXT,
  user_id INT REFERENCES app_user(user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX idx_move_jc ON stock_movement(jewel_code_id, moved_at DESC);
CREATE INDEX idx_move_type ON stock_movement(move_type, moved_at DESC);
CREATE OR REPLACE FUNCTION trg_apply_movement() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_state stock_state;
BEGIN
  SELECT stock_state INTO v_state FROM jewel_code WHERE jewel_code_id=NEW.jewel_code_id FOR UPDATE;
  IF v_state IN ('SOLD','MELTED','LOST') THEN
    RAISE EXCEPTION 'Jewel code % is % - terminal, cannot move it. Create a new jewel code.',
      (SELECT jewel_code FROM jewel_code WHERE jewel_code_id=NEW.jewel_code_id), v_state;
  END IF;
  UPDATE jewel_code SET
    stock_state = NEW.resulting_state,
    location_id = CASE WHEN NEW.resulting_state IN ('SOLD','MELTED','LOST')
                       THEN NULL ELSE COALESCE(NEW.to_location_id, location_id) END,
    received_on = CASE WHEN NEW.move_type='RECEIPT' AND received_on IS NULL
                       THEN NEW.moved_at::date ELSE received_on END,
    disposed_on = CASE WHEN NEW.resulting_state IN ('SOLD','MELTED','LOST')
                       THEN NEW.moved_at::date ELSE disposed_on END,
    updated_at = now()
  WHERE jewel_code_id = NEW.jewel_code_id;
  RETURN NEW;
END $$;
CREATE TRIGGER apply_movement AFTER INSERT ON stock_movement
FOR EACH ROW EXECUTE FUNCTION trg_apply_movement();
CREATE TABLE sale (
  sale_id BIGSERIAL PRIMARY KEY,
  jewel_code_id INT NOT NULL UNIQUE REFERENCES jewel_code(jewel_code_id),
  bom_version_at_sale INT NOT NULL,
  sold_on DATE NOT NULL,
  location_id INT NOT NULL REFERENCES location(location_id),
  customer_name TEXT, customer_phone TEXT,
  salesperson_id INT REFERENCES app_user(user_id),
  sold_price   NUMERIC(14,2) NOT NULL,
  discount_amt NUMERIC(14,2) NOT NULL DEFAULT 0,
  cost_at_sale NUMERIC(14,2) NOT NULL,
  margin_amt NUMERIC(14,2) GENERATED ALWAYS AS (sold_price - discount_amt - cost_at_sale) STORED,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE repair_job (
  repair_job_id BIGSERIAL PRIMARY KEY,
  job_no TEXT NOT NULL UNIQUE,
  jewel_code_id INT NOT NULL REFERENCES jewel_code(jewel_code_id),
  from_bom_version INT NOT NULL,
  to_bom_version INT,
  opened_on DATE NOT NULL DEFAULT CURRENT_DATE,
  closed_on DATE,
  vendor_id INT REFERENCES vendor(vendor_id),
  return_location_id INT REFERENCES location(location_id),
  fault_description TEXT NOT NULL,
  work_done TEXT,
  labour_cost NUMERIC(14,2) NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','WITH_VENDOR','DONE','CANCELLED')),
  opened_by INT REFERENCES app_user(user_id),
  closed_by INT REFERENCES app_user(user_id),
  tat_days INT GENERATED ALWAYS AS (closed_on - opened_on) STORED);
CREATE TABLE repair_material_change (
  change_id BIGSERIAL PRIMARY KEY,
  repair_job_id BIGINT NOT NULL REFERENCES repair_job(repair_job_id) ON DELETE CASCADE,
  action TEXT NOT NULL CHECK (action IN ('REMOVE','ADD')),
  material_id INT NOT NULL REFERENCES material(material_id),
  size_band TEXT NOT NULL DEFAULT '',
  pcs INT, qty_value NUMERIC(12,4), qty_uom uom NOT NULL,
  cost_rate NUMERIC(14,4), sale_rate NUMERIC(14,4),
  returned_to_stock BOOLEAN NOT NULL DEFAULT TRUE,
  remarks TEXT);
ALTER TABLE bom_version
  ADD CONSTRAINT fk_bom_repair FOREIGN KEY (repair_job_id) REFERENCES repair_job(repair_job_id);;
