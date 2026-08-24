-- A function with a mutable search_path can be tricked into resolving a
-- table name to an attacker-controlled schema. Pin every one of ours.
ALTER FUNCTION app.setting_int(TEXT,INT)            SET search_path = app, public;
ALTER FUNCTION app.setting_num(TEXT,NUMERIC)        SET search_path = app, public;
ALTER FUNCTION app.line_weight_gm(NUMERIC,app.uom)  SET search_path = app, public;
ALTER FUNCTION app.trg_check_line_uom()             SET search_path = app, public;
ALTER FUNCTION app.recost_jewel(INT,INT,INT)        SET search_path = app, public;
ALTER FUNCTION app.trg_apply_movement()             SET search_path = app, public;
ALTER FUNCTION app.complete_repair(BIGINT,INT)      SET search_path = app, public;
ALTER FUNCTION app.melt_jewel(INT,INT,TEXT)         SET search_path = app, public;

-- Tables that carry no policy currently deny everything, which is the
-- correct default. Give the ones the app genuinely reads a policy so the
-- intent is explicit rather than accidental.
CREATE POLICY ref_read ON app.style_tag              FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.jewel_code_certificate FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.catalogue_template     FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.catalogue              FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY ref_read ON app.catalogue_item         FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY self_read ON app.user_location         FOR SELECT TO authenticated
  USING (user_id = app.current_user_id() OR app.is_admin());
CREATE POLICY mat_read  ON app.material_inventory    FOR SELECT TO authenticated
  USING (app.has_cap('materials'));
CREATE POLICY prod_read ON app.job_card              FOR SELECT TO authenticated
  USING (app.has_cap('materials'));
CREATE POLICY repair_read ON app.repair_job          FOR SELECT TO authenticated
  USING (app.has_cap('materials'));
CREATE POLICY repair_chg_read ON app.repair_material_change FOR SELECT TO authenticated
  USING (app.has_cap('materials'));
CREATE POLICY count_read ON app.stock_count          FOR SELECT TO authenticated USING (TRUE);
CREATE POLICY scan_read  ON app.stock_count_scan     FOR SELECT TO authenticated USING (TRUE);;
