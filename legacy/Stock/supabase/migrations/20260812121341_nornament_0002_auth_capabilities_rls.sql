SET search_path TO app, public;
ALTER TABLE app_user
  ADD COLUMN IF NOT EXISTS auth_uid UUID UNIQUE,
  ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE app_user ALTER COLUMN password_hash DROP NOT NULL;
CREATE INDEX IF NOT EXISTS idx_app_user_auth ON app_user(auth_uid);
CREATE OR REPLACE FUNCTION app.current_user_id()
RETURNS INT LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT u.user_id FROM app_user u
   WHERE u.auth_uid = auth.uid() AND u.is_active
   LIMIT 1;
$$;
CREATE OR REPLACE FUNCTION app.has_cap(p_cap TEXT)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT COALESCE(
    (SELECT CASE p_cap
       WHEN 'cost'      THEN r.can_view_cost_price
       WHEN 'sale'      THEN r.can_view_sale_price
       WHEN 'materials' THEN r.can_view_material_breakup
       WHEN 'vendor'    THEN r.can_view_vendor
       WHEN 'margin'    THEN r.can_view_margin
       WHEN 'melt'      THEN r.can_melt
       WHEN 'editBom'   THEN r.can_edit_bom
       WHEN 'adjust'    THEN r.can_adjust_stock
       ELSE FALSE END
     FROM app_user u JOIN role r USING (role_id)
     WHERE u.auth_uid = auth.uid() AND u.is_active), FALSE);
$$;
CREATE OR REPLACE FUNCTION app.visible_locations()
RETURNS SETOF INT LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  WITH me AS (SELECT user_id, home_location_id FROM app_user
               WHERE auth_uid = auth.uid() AND is_active)
  SELECT l.location_id FROM location l
  WHERE EXISTS (SELECT 1 FROM me WHERE home_location_id IS NULL)
     OR l.location_id IN (SELECT home_location_id FROM me)
     OR l.location_id IN (SELECT ul.location_id FROM user_location ul
                          JOIN me ON me.user_id = ul.user_id);
$$;
CREATE OR REPLACE FUNCTION app.is_admin()
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT COALESCE((SELECT r.is_system FROM app_user u JOIN role r USING (role_id)
                   WHERE u.auth_uid = auth.uid() AND u.is_active), FALSE);
$$;
DO $$
DECLARE t RECORD;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='app' LOOP
    EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY', t.tablename);
    EXECUTE format('REVOKE ALL ON app.%I FROM anon, authenticated', t.tablename);
  END LOOP;
END $$;
REVOKE ALL ON SCHEMA app FROM anon, authenticated;
GRANT USAGE ON SCHEMA app TO authenticated;
CREATE POLICY jewel_visible ON app.jewel_code FOR SELECT TO authenticated
  USING (location_id IS NULL OR location_id IN (SELECT app.visible_locations()));
CREATE POLICY jewel_write ON app.jewel_code FOR UPDATE TO authenticated
  USING (app.has_cap('editBom') OR app.has_cap('adjust'))
  WITH CHECK (app.has_cap('editBom') OR app.has_cap('adjust'));
CREATE POLICY bom_read ON app.jewel_material_line FOR SELECT TO authenticated
  USING (app.has_cap('materials'));
CREATE POLICY bomver_read ON app.bom_version FOR SELECT TO authenticated
  USING (app.has_cap('materials'));
CREATE POLICY bom_write ON app.jewel_material_line FOR ALL TO authenticated
  USING (app.has_cap('editBom')) WITH CHECK (app.has_cap('editBom'));
CREATE POLICY bomver_write ON app.bom_version FOR ALL TO authenticated
  USING (app.has_cap('editBom')) WITH CHECK (app.has_cap('editBom'));
CREATE POLICY ratecard_read ON app.rate_card FOR SELECT TO authenticated
  USING (card_type = 'SALE' AND app.has_cap('sale') OR card_type = 'COST' AND app.has_cap('cost'));
CREATE POLICY ratecardline_read ON app.rate_card_line FOR SELECT TO authenticated
  USING (EXISTS (SELECT 1 FROM app.rate_card c WHERE c.rate_card_id = rate_card_line.rate_card_id
                 AND (c.card_type='SALE' AND app.has_cap('sale')
                   OR c.card_type='COST' AND app.has_cap('cost'))));
CREATE POLICY ref_read ON app.location   FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.category   FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.collection FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.tag        FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.style      FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.material   FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.metal_purity FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.uom_conversion FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.system_setting FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.media_asset FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.stock_movement FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY vendor_read ON app.vendor FOR SELECT TO authenticated
  USING (app.has_cap('vendor'));
CREATE POLICY sale_read ON app.sale FOR SELECT TO authenticated
  USING (app.has_cap('sale'));
CREATE POLICY sale_write ON app.sale FOR INSERT TO authenticated
  WITH CHECK (app.has_cap('adjust'));
CREATE POLICY melt_read ON app.melt_record FOR SELECT TO authenticated
  USING (app.has_cap('melt') OR app.has_cap('cost'));
CREATE POLICY melt_write ON app.melt_record FOR INSERT TO authenticated
  WITH CHECK (app.has_cap('melt'));
CREATE POLICY user_self ON app.app_user FOR SELECT TO authenticated
  USING (auth_uid = auth.uid() OR app.is_admin());
CREATE POLICY role_read ON app.role FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY module_read ON app.module FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY rmp_read ON app.role_module_permission FOR SELECT TO authenticated USING (TRUE);
ALTER TABLE activity_log
  ADD COLUMN IF NOT EXISTS ip INET,
  ADD COLUMN IF NOT EXISTS user_agent TEXT,
  ADD COLUMN IF NOT EXISTS export_id TEXT,
  ADD COLUMN IF NOT EXISTS row_count INT,
  ADD COLUMN IF NOT EXISTS detail TEXT;
CREATE POLICY audit_read ON app.activity_log FOR SELECT TO authenticated
  USING (app.is_admin());
CREATE OR REPLACE FUNCTION app.log(p_action TEXT, p_table TEXT, p_pk TEXT,
                                   p_detail TEXT DEFAULT NULL, p_export TEXT DEFAULT NULL,
                                   p_rows INT DEFAULT NULL)
RETURNS VOID LANGUAGE sql SECURITY DEFINER SET search_path = app, public AS $$
  INSERT INTO activity_log (table_name, record_pk, action, user_id, detail, export_id, row_count,
                            ip, user_agent)
  VALUES (p_table, p_pk, p_action, app.current_user_id(), p_detail, p_export, p_rows,
          NULLIF(current_setting('request.headers', true)::json->>'x-forwarded-for','')::inet,
          current_setting('request.headers', true)::json->>'user-agent');
$$;
CREATE OR REPLACE FUNCTION app.pure_gold_rate() RETURNS NUMERIC
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT COALESCE((SELECT value::numeric FROM system_setting WHERE key='pure_gold_rate'), 0);
$$;
CREATE OR REPLACE FUNCTION app.alloy_sale_rate(p_karat TEXT) RETURNS NUMERIC
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT ROUND(app.pure_gold_rate() * COALESCE(
    (SELECT sale_factor FROM metal_purity WHERE karat = p_karat), 0), 0);
$$;
CREATE OR REPLACE FUNCTION app.live_sale_price(p_jc INT, p_version INT DEFAULT NULL)
RETURNS NUMERIC LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  WITH v AS (
    SELECT COALESCE(p_version,(SELECT current_bom_version FROM jewel_code WHERE jewel_code_id=p_jc)) AS n,
           (SELECT metal_purity FROM jewel_code WHERE jewel_code_id=p_jc) AS karat),
  metal AS (
    SELECT COALESCE(SUM(line_weight_gm(l.qty_value,l.qty_uom)),0) AS gm
    FROM jewel_material_line l JOIN material m USING (material_id), v
    WHERE l.jewel_code_id=p_jc AND l.version_no=v.n AND m.mat_class='METAL')
  SELECT COALESCE(SUM(ROUND(
    CASE
      WHEN m.mat_class='METAL'  THEN app.alloy_sale_rate(v.karat) * COALESCE(l.qty_value,0)
      WHEN l.basis='BY_NET_METAL_WT' THEN COALESCE(l.sale_rate,0) * (SELECT gm FROM metal)
      WHEN l.basis='BY_PIECE'   THEN COALESCE(l.sale_rate,0) * COALESCE(l.pcs,0)
      ELSE COALESCE(l.sale_rate,0) * COALESCE(l.qty_value,0)
    END, setting_int('line_rounding_dp',0))),0)
  FROM jewel_material_line l JOIN material m USING (material_id), v
  WHERE l.jewel_code_id=p_jc AND l.version_no=v.n;
$$;
GRANT EXECUTE ON FUNCTION app.has_cap(TEXT), app.is_admin(), app.current_user_id(),
  app.visible_locations(), app.pure_gold_rate(), app.alloy_sale_rate(TEXT),
  app.log(TEXT,TEXT,TEXT,TEXT,TEXT,INT), app.live_sale_price(INT,INT)
  TO authenticated;;
