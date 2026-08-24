SET search_path TO app, public;
CREATE OR REPLACE FUNCTION complete_repair(p_job BIGINT, p_user INT)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE
  v_jc INT; v_from INT; v_new INT; r RECORD; v_line INT; v_home INT;
BEGIN
  SELECT jewel_code_id, from_bom_version INTO v_jc, v_from
    FROM repair_job WHERE repair_job_id=p_job AND status<>'DONE';
  IF v_jc IS NULL THEN RAISE EXCEPTION 'Repair job % not found or already closed', p_job; END IF;
  SELECT COALESCE(MAX(version_no),0)+1 INTO v_new FROM bom_version WHERE jewel_code_id=v_jc;
  UPDATE bom_version SET is_current=FALSE WHERE jewel_code_id=v_jc AND is_current;
  INSERT INTO bom_version (jewel_code_id, version_no, reason, note, repair_job_id,
                           cost_rate_card_id, sale_rate_card_id, is_current, created_by)
  SELECT v_jc, v_new, 'REPAIR',
         'Auto-created by repair job '||(SELECT job_no FROM repair_job WHERE repair_job_id=p_job),
         p_job, cost_rate_card_id, sale_rate_card_id, TRUE, p_user
  FROM bom_version WHERE jewel_code_id=v_jc AND version_no=v_from;
  INSERT INTO jewel_material_line (jewel_code_id, version_no, line_no, material_id, size_band,
                                   pcs, qty_value, qty_uom, basis, cost_rate, sale_rate, remarks)
  SELECT v_jc, v_new, line_no, material_id, size_band, pcs, qty_value, qty_uom, basis,
         cost_rate, sale_rate, remarks
  FROM jewel_material_line WHERE jewel_code_id=v_jc AND version_no=v_from;
  FOR r IN SELECT * FROM repair_material_change
            WHERE repair_job_id=p_job AND action='REMOVE' LOOP
    UPDATE jewel_material_line l
       SET qty_value = COALESCE(l.qty_value,0) - COALESCE(r.qty_value,0),
           pcs       = COALESCE(l.pcs,0) - COALESCE(r.pcs,0)
     WHERE l.jewel_code_id=v_jc AND l.version_no=v_new
       AND l.material_id=r.material_id AND l.size_band=r.size_band;
    DELETE FROM jewel_material_line
     WHERE jewel_code_id=v_jc AND version_no=v_new
       AND material_id=r.material_id AND size_band=r.size_band
       AND COALESCE(qty_value,0) <= 0 AND COALESCE(pcs,0) <= 0;
  END LOOP;
  FOR r IN SELECT * FROM repair_material_change
            WHERE repair_job_id=p_job AND action='ADD' LOOP
    UPDATE jewel_material_line l
       SET qty_value = COALESCE(l.qty_value,0) + COALESCE(r.qty_value,0),
           pcs       = COALESCE(l.pcs,0) + COALESCE(r.pcs,0),
           cost_rate = COALESCE(r.cost_rate, l.cost_rate),
           sale_rate = COALESCE(r.sale_rate, l.sale_rate)
     WHERE l.jewel_code_id=v_jc AND l.version_no=v_new
       AND l.material_id=r.material_id AND l.size_band=r.size_band;
    IF NOT FOUND THEN
      SELECT COALESCE(MAX(line_no),0)+1 INTO v_line
        FROM jewel_material_line WHERE jewel_code_id=v_jc AND version_no=v_new;
      INSERT INTO jewel_material_line (jewel_code_id, version_no, line_no, material_id,
              size_band, pcs, qty_value, qty_uom, basis, cost_rate, sale_rate, remarks)
      VALUES (v_jc, v_new, v_line, r.material_id, r.size_band, r.pcs, r.qty_value,
              r.qty_uom, 'BY_QTY', r.cost_rate, r.sale_rate, 'Added by repair');
    END IF;
  END LOOP;
  UPDATE jewel_code SET current_bom_version=v_new, updated_at=now() WHERE jewel_code_id=v_jc;
  PERFORM recost_jewel(v_jc, v_new, p_user);
  UPDATE repair_job SET status='DONE', to_bom_version=v_new,
         closed_on=CURRENT_DATE, closed_by=p_user
   WHERE repair_job_id=p_job;
  SELECT from_location_id INTO v_home
    FROM stock_movement
   WHERE jewel_code_id=v_jc AND move_type='REPAIR_OUT'
   ORDER BY movement_id DESC LIMIT 1;
  INSERT INTO stock_movement (jewel_code_id, move_type, from_location_id, to_location_id,
                              resulting_state, reason, user_id, reference_no)
  SELECT v_jc,'REPAIR_IN', jc.location_id,
         COALESCE(v_home, rj.return_location_id, jc.location_id),'IN_STOCK',
         'Repair completed', p_user, rj.job_no
  FROM jewel_code jc, repair_job rj
  WHERE jc.jewel_code_id=v_jc AND rj.repair_job_id=p_job;
  RETURN v_new;
END $$;
CREATE TABLE melt_record (
  melt_id BIGSERIAL PRIMARY KEY,
  jewel_code_id INT NOT NULL UNIQUE REFERENCES jewel_code(jewel_code_id),
  bom_version_at_melt INT NOT NULL,
  melted_on DATE NOT NULL DEFAULT CURRENT_DATE,
  location_id INT REFERENCES location(location_id),
  reason TEXT NOT NULL CHECK (length(btrim(reason)) >= 10),
  cost_written_off NUMERIC(14,2),
  authorised_by INT NOT NULL REFERENCES app_user(user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE OR REPLACE FUNCTION melt_jewel(p_jc INT, p_user INT, p_reason TEXT)
RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE v_ok BOOLEAN; v_state stock_state; v_ver INT; v_loc INT; v_cost NUMERIC; v_id BIGINT;
BEGIN
  SELECT r.can_melt INTO v_ok FROM app_user u JOIN role r USING (role_id) WHERE u.user_id=p_user;
  IF NOT COALESCE(v_ok,FALSE) THEN
    RAISE EXCEPTION 'User % is not authorised to melt. Admin only.', p_user;
  END IF;
  IF p_reason IS NULL OR length(btrim(p_reason)) < 10 THEN
    RAISE EXCEPTION 'A melt reason of at least 10 characters is required.';
  END IF;
  SELECT stock_state, current_bom_version, location_id INTO v_state, v_ver, v_loc
    FROM jewel_code WHERE jewel_code_id=p_jc FOR UPDATE;
  IF v_state IN ('SOLD','MELTED','LOST') THEN
    RAISE EXCEPTION 'Cannot melt: jewel code is already %.', v_state;
  END IF;
  SELECT total_cost_price INTO v_cost FROM bom_version
   WHERE jewel_code_id=p_jc AND version_no=v_ver;
  INSERT INTO melt_record (jewel_code_id, bom_version_at_melt, location_id, reason,
                           cost_written_off, authorised_by)
  VALUES (p_jc, v_ver, v_loc, p_reason, v_cost, p_user)
  RETURNING melt_id INTO v_id;
  INSERT INTO stock_movement (jewel_code_id, move_type, from_location_id, resulting_state,
                              reason, user_id)
  VALUES (p_jc,'MELT', v_loc,'MELTED', p_reason, p_user);
  RETURN v_id;
END $$;
CREATE TABLE stock_count (
  count_id SERIAL PRIMARY KEY,
  count_ref TEXT NOT NULL UNIQUE,
  location_id INT NOT NULL REFERENCES location(location_id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED','CANCELLED')),
  counted_by INT REFERENCES app_user(user_id),
  approved_by INT REFERENCES app_user(user_id),
  notes TEXT);
CREATE TABLE stock_count_scan (
  scan_id BIGSERIAL PRIMARY KEY,
  count_id INT NOT NULL REFERENCES stock_count(count_id) ON DELETE CASCADE,
  jewel_code_id INT NOT NULL REFERENCES jewel_code(jewel_code_id),
  scanned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  scanned_by INT REFERENCES app_user(user_id),
  UNIQUE (count_id, jewel_code_id));
CREATE OR REPLACE VIEW vw_stock_count_variance AS
WITH expected AS (
  SELECT sc.count_id, jc.jewel_code_id
  FROM stock_count sc JOIN jewel_code jc
    ON jc.location_id = sc.location_id
   AND jc.stock_state IN ('IN_STOCK','RESERVED')),
scanned AS (
  SELECT count_id, jewel_code_id FROM stock_count_scan),
combined AS (
  SELECT COALESCE(e.count_id, s.count_id)           AS count_id,
         COALESCE(e.jewel_code_id, s.jewel_code_id) AS jewel_code_id,
         (e.jewel_code_id IS NOT NULL) AS is_expected,
         (s.jewel_code_id IS NOT NULL) AS is_scanned
  FROM expected e
  FULL JOIN scanned s
    ON s.count_id = e.count_id AND s.jewel_code_id = e.jewel_code_id)
SELECT c.count_id, sc.count_ref, l.name AS counted_location,
       jc.jewel_code, jc.stock_state, jcl.name AS system_location,
       CASE WHEN c.is_expected AND c.is_scanned THEN 'FOUND'
            WHEN c.is_expected                  THEN 'MISSING'
            ELSE 'UNEXPECTED' END AS variance,
       b.total_cost_price AS carried_cost
FROM combined c
JOIN stock_count sc ON sc.count_id = c.count_id
JOIN location l     ON l.location_id = sc.location_id
JOIN jewel_code jc  ON jc.jewel_code_id = c.jewel_code_id
LEFT JOIN location jcl ON jcl.location_id = jc.location_id
LEFT JOIN bom_version b ON b.jewel_code_id = jc.jewel_code_id AND b.is_current;;
