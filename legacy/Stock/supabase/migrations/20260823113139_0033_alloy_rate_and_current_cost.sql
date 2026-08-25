
-- ─────────────────────────────────────────────────────────────────────────
-- 0033  Point every live pricing path at the right metal, and add the
--       current cost — what the piece would cost to make this morning.
--
-- 0032 corrected the stored line rates but left app.alloy_sale_rate()
-- multiplying EVERY purity by the pure gold rate. With 925 now carrying a
-- 1.0 sale factor that returned 15,481/g for silver — worse than the bug it
-- replaced. api.jewel.sale_price reads that function, so it has to change
-- before anything else is built on top.
-- ─────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION app.alloy_sale_rate(p_karat TEXT)
RETURNS NUMERIC
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT COALESCE(app.metal_rate(p_karat, 'SALE'), 0);
$$;
COMMENT ON FUNCTION app.alloy_sale_rate(TEXT) IS
  'Kept for callers that already use this name. Now delegates to '
  'app.metal_rate, which reads the rate of the metal the purity belongs to '
  'instead of assuming gold.';

CREATE OR REPLACE FUNCTION app.alloy_cost_rate(p_karat TEXT)
RETURNS NUMERIC
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT COALESCE(app.metal_rate(p_karat, 'COST'), 0);
$$;

-- ── current cost ─────────────────────────────────────────────────────────
-- Everything priced as the frozen BOM says, EXCEPT metal, which is repriced
-- at today's rate. This is the replacement cost: what an identical piece
-- would cost to make now. Nothing about it is stored — it moves when the
-- rate moves, which is the entire point.
CREATE OR REPLACE FUNCTION app.current_cost(p_jc INTEGER, p_version INTEGER DEFAULT NULL)
RETURNS NUMERIC
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  WITH v AS (
    SELECT COALESCE(p_version,
             (SELECT current_bom_version FROM jewel_code WHERE jewel_code_id = p_jc)) AS n,
           (SELECT metal_purity FROM jewel_code WHERE jewel_code_id = p_jc) AS karat),
  metal AS (
    SELECT COALESCE(SUM(line_weight_gm(l.qty_value, l.qty_uom)), 0) AS gm
      FROM jewel_material_line l JOIN material m USING (material_id), v
     WHERE l.jewel_code_id = p_jc AND l.version_no = v.n AND m.mat_class = 'METAL')
  SELECT COALESCE(SUM(ROUND(
    CASE
      WHEN m.mat_class = 'METAL'      THEN app.alloy_cost_rate(v.karat) * COALESCE(l.qty_value,0)
      WHEN l.basis = 'BY_NET_METAL_WT' THEN COALESCE(l.cost_rate,0) * (SELECT gm FROM metal)
      WHEN l.basis = 'BY_PIECE'        THEN COALESCE(l.cost_rate,0) * COALESCE(l.pcs,0)
      WHEN l.basis = 'FLAT'            THEN COALESCE(l.cost_rate,0)
      ELSE COALESCE(l.cost_rate,0) * COALESCE(l.qty_value,0)
    END, setting_int('line_rounding_dp',0))), 0)
  FROM jewel_material_line l JOIN material m USING (material_id), v
 WHERE l.jewel_code_id = p_jc AND l.version_no = v.n;
$$;
COMMENT ON FUNCTION app.current_cost(INTEGER,INTEGER) IS
  'Replacement cost at today''s metal rates. Frozen cost says what the piece '
  'did cost; this says what it would cost now. Quote off the frozen one and '
  'the margin is a story about a metal price that no longer exists.';

-- ── metals, readable by the app ──────────────────────────────────────────
CREATE OR REPLACE VIEW api.metal
WITH (security_invoker = false) AS
SELECT m.code, m.name, m.pure_rate, m.rate_as_on, m.unit, m.note, m.is_active
  FROM app.metal m
 WHERE app.has_cap('sale') OR app.has_cap('cost');

CREATE OR REPLACE VIEW api.metal_purity
WITH (security_invoker = false) AS
SELECT mp.metal, mp.karat, mp.sale_factor, mp.true_fineness, mp.sort_order,
       app.metal_rate(mp.karat,'SALE') AS sale_rate,
       app.metal_rate(mp.karat,'COST') AS cost_rate
  FROM app.metal_purity mp
 WHERE app.has_cap('sale') OR app.has_cap('cost');

GRANT SELECT ON api.metal, api.metal_purity TO anon, authenticated;

-- ── admin sets a rate ────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION app.set_metal_rate(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_code TEXT := upper(btrim(coalesce(p->>'code','')));
        v_rate NUMERIC := nullif(p->>'pure_rate','')::numeric;
        v_old  NUMERIC;
BEGIN
  IF NOT app.is_admin() THEN
    RAISE EXCEPTION 'Only an admin can change a metal rate.';
  END IF;
  SELECT pure_rate INTO v_old FROM app.metal WHERE code = v_code;
  IF v_old IS NULL THEN RAISE EXCEPTION 'No metal called "%".', v_code; END IF;
  IF v_rate IS NULL OR v_rate <= 0 THEN
    RAISE EXCEPTION 'A rate must be a number greater than zero.';
  END IF;
  -- a fat finger on the metal rate reprices the whole catalogue at once
  IF v_rate > v_old * 3 OR v_rate < v_old / 3 THEN
    RAISE EXCEPTION '% would move from % to % — more than three times. If that is right, set it in two steps.',
      v_code, v_old, v_rate;
  END IF;
  UPDATE app.metal SET pure_rate = v_rate, rate_as_on = now() WHERE code = v_code;
  PERFORM app.log('UPDATE','metal', v_code, v_old::text || ' -> ' || v_rate::text || ' per gram');
  RETURN jsonb_build_object('ok', true, 'code', v_code, 'was', v_old, 'now', v_rate);
END $fn$;

CREATE OR REPLACE FUNCTION app.set_purity(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_k TEXT := upper(btrim(coalesce(p->>'karat','')));
        v_m TEXT := upper(btrim(coalesce(p->>'metal','')));
        v_s NUMERIC := nullif(p->>'sale_factor','')::numeric;
        v_f NUMERIC := nullif(p->>'true_fineness','')::numeric;
BEGIN
  IF NOT app.is_admin() THEN
    RAISE EXCEPTION 'Only an admin can change a purity.';
  END IF;
  IF v_s IS NULL OR v_s <= 0 OR v_s > 2 OR v_f IS NULL OR v_f <= 0 OR v_f > 1 THEN
    RAISE EXCEPTION 'Sale factor must be above 0 (and at most 2); true fineness must be above 0 and at most 1.';
  END IF;
  IF EXISTS (SELECT 1 FROM app.metal_purity WHERE karat = v_k) THEN
    UPDATE app.metal_purity
       SET sale_factor = v_s, true_fineness = v_f,
           metal = COALESCE(nullif(v_m,''), metal)
     WHERE karat = v_k;
  ELSE
    IF v_m = '' OR NOT EXISTS (SELECT 1 FROM app.metal WHERE code = v_m) THEN
      RAISE EXCEPTION 'A new purity needs a metal it belongs to.';
    END IF;
    INSERT INTO app.metal_purity (karat, sale_factor, true_fineness, metal)
    VALUES (v_k, v_s, v_f, v_m);
  END IF;
  PERFORM app.log('UPDATE','metal_purity', v_k,
                  'sale ' || v_s::text || ' / fineness ' || v_f::text);
  RETURN jsonb_build_object('ok', true, 'karat', v_k,
    'sale_rate', app.metal_rate(v_k,'SALE'), 'cost_rate', app.metal_rate(v_k,'COST'));
END $fn$;

CREATE OR REPLACE FUNCTION api.set_metal_rate(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public
AS $$ SELECT app.set_metal_rate(p) $$;
CREATE OR REPLACE FUNCTION api.set_purity(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public
AS $$ SELECT app.set_purity(p) $$;

GRANT EXECUTE ON FUNCTION api.set_metal_rate(jsonb), api.set_purity(jsonb) TO anon, authenticated;
REVOKE ALL ON FUNCTION app.set_metal_rate(jsonb), app.set_purity(jsonb) FROM anon, authenticated;
;
