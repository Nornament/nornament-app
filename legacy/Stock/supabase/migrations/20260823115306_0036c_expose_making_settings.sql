
-- The making default has to reach the app, and an admin has to be able to
-- change it. api.reference only exposes three settings keys by name.
CREATE OR REPLACE VIEW api.reference
WITH (security_invoker = false) AS
 SELECT 'category'::text AS kind, category.code, category.name AS label,
        NULL::text AS extra, category.sort_order AS ord FROM app.category
UNION ALL
 SELECT 'location', location.code, location.name, location.kind, location.location_id
   FROM app.location WHERE location.is_active
UNION ALL
 SELECT 'karat', mp.karat, mp.karat, mp.sale_factor::text, mp.sort_order
   FROM app.metal_purity mp
UNION ALL
 SELECT 'colour', v.c, v.c, NULL::text, 0
   FROM (VALUES ('Yellow'),('White'),('Rose'),('Two-tone')) v(c)
UNION ALL
 SELECT 'material', material.item_code, material.item_name,
        (material.mat_class::text || '|') || material.default_uom::text, material.material_id
   FROM app.material WHERE material.is_active
UNION ALL
 SELECT DISTINCT 'size_band', l.size_band, l.size_band, m.item_code, 0
   FROM app.rate_card_line l JOIN app.material m USING (material_id)
  WHERE l.size_band <> ''
UNION ALL
 SELECT 'basis', v.b, v.b, NULL::text, 0
   FROM (VALUES ('BY_QTY'),('BY_NET_METAL_WT'),('BY_PIECE'),('FLAT')) v(b)
UNION ALL
 SELECT 'uom', v.u, v.u, NULL::text, 0
   FROM (VALUES ('CT'),('GM'),('RATTI'),('PCS')) v(u)
UNION ALL
 SELECT 'style', s.style_code, COALESCE(s.name, s.style_code),
        ((SELECT c.name FROM app.category c WHERE c.category_id = s.category_id) || '|')
        || s.nos_min_qty, s.style_id
   FROM app.style s WHERE s.is_active
UNION ALL
 SELECT 'setting', ss.key, ss.value, NULL::text, 0
   FROM app.system_setting ss
  WHERE ss.key = ANY (ARRAY['pure_gold_rate','pure_gold_rate_as_on','line_rounding_dp',
                            'making_rate_default','making_basis_default'])
    AND app.has_cap('sale')
UNION ALL
 SELECT 'rate', (m.item_code || '|') || l.size_band, l.rate::text, c.card_type, 0
   FROM app.rate_card_line l JOIN app.rate_card c USING (rate_card_id)
   JOIN app.material m USING (material_id)
  WHERE c.card_type = 'COST' AND app.has_cap('cost')
     OR c.card_type = 'SALE' AND app.has_cap('sale');

GRANT SELECT ON api.reference TO anon, authenticated;

CREATE OR REPLACE FUNCTION app.set_setting(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_key TEXT := btrim(coalesce(p->>'key',''));
        v_val TEXT := btrim(coalesce(p->>'value',''));
        v_old TEXT;
BEGIN
  IF NOT app.is_admin() THEN
    RAISE EXCEPTION 'Only an admin can change a setting.';
  END IF;
  -- a deliberately short list: these are the ones with a screen behind them
  IF v_key NOT IN ('making_rate_default','making_basis_default',
                   'line_rounding_dp','gross_wt_tolerance_gm') THEN
    RAISE EXCEPTION 'Setting "%" is not one this screen may change.', v_key;
  END IF;
  IF v_key = 'making_rate_default' AND (v_val !~ '^[0-9]+(\.[0-9]+)?$' OR v_val::numeric <= 0) THEN
    RAISE EXCEPTION 'The making rate must be a number greater than zero.';
  END IF;
  IF v_key = 'making_basis_default' AND v_val NOT IN ('BY_NET_METAL_WT','FLAT') THEN
    RAISE EXCEPTION 'Making is charged either per gram (BY_NET_METAL_WT) or as a flat amount (FLAT).';
  END IF;
  SELECT value INTO v_old FROM app.system_setting WHERE key = v_key;
  INSERT INTO app.system_setting (key, value) VALUES (v_key, v_val)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
  PERFORM app.log('UPDATE','system_setting', v_key,
                  COALESCE(v_old,'(unset)')||' -> '||v_val);
  RETURN jsonb_build_object('ok',true,'key',v_key,'was',v_old,'now',v_val);
END $fn$;

CREATE OR REPLACE FUNCTION api.set_setting(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public AS $$ SELECT app.set_setting(p) $$;
GRANT EXECUTE ON FUNCTION api.set_setting(jsonb) TO anon, authenticated;
REVOKE ALL ON FUNCTION app.set_setting(jsonb) FROM anon, authenticated;
;
