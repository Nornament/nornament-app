
-- ─────────────────────────────────────────────────────────────────────────
-- 0036  Making defaults, and pricing scenarios
--
-- Making is ₹1,500/g by default, changeable at any time, and overridable on
-- any single line — per gram or a flat amount for the piece.
--
-- A scenario turns cost into an asking price. Two methods only:
--   CHART        take the sale rates as written in a rate chart
--   VALUE_ADDED  target a markup on cost-minus-metal, absorbed by stones
-- Metal is never marked up by either. That is the rule the whole model rests
-- on: gold and silver pass through at their live rate.
-- ─────────────────────────────────────────────────────────────────────────

INSERT INTO app.system_setting (key, value) VALUES
  ('making_rate_default', '1500'),
  ('making_basis_default', 'BY_NET_METAL_WT')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS app.scenario (
  scenario_id  SERIAL PRIMARY KEY,
  code         TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  method       TEXT NOT NULL CHECK (method IN ('CHART','VALUE_ADDED')),
  chart_id     INT REFERENCES app.rate_chart(chart_id),
  target_pct   NUMERIC(8,3),          -- VALUE_ADDED: markup over value-added cost
  spread_over  TEXT[] NOT NULL DEFAULT ARRAY['DIAMOND','POLKI','SETTING','PURAI'],
  spread_by    TEXT NOT NULL DEFAULT 'COST' CHECK (spread_by IN ('COST','WEIGHT')),
  min_multiple NUMERIC(8,3) NOT NULL DEFAULT 1.0,   -- stones never below cost
  max_multiple NUMERIC(8,3) NOT NULL DEFAULT 8.0,   -- and never absurd
  is_default   BOOLEAN NOT NULL DEFAULT false,
  is_active    BOOLEAN NOT NULL DEFAULT true,
  note         TEXT,
  CHECK (method <> 'VALUE_ADDED' OR target_pct IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS scenario_one_default
  ON app.scenario((is_default)) WHERE is_default;

-- who may price with it, and who may switch a piece onto it
CREATE TABLE IF NOT EXISTS app.scenario_role (
  scenario_id INT NOT NULL REFERENCES app.scenario(scenario_id) ON DELETE CASCADE,
  role_id     INT NOT NULL REFERENCES app.role(role_id),
  may_see     BOOLEAN NOT NULL DEFAULT true,
  may_switch  BOOLEAN NOT NULL DEFAULT false,
  PRIMARY KEY (scenario_id, role_id)
);

ALTER TABLE app.jewel_code
  ADD COLUMN IF NOT EXISTS scenario_id INT REFERENCES app.scenario(scenario_id);
COMMENT ON COLUMN app.jewel_code.scenario_id IS
  'Overrides the default scenario for this one piece. Null means use the default.';

INSERT INTO app.scenario (code, name, method, chart_id, is_default, note)
SELECT 'RETAIL', 'Retail', 'CHART', (SELECT chart_id FROM app.rate_chart WHERE is_default),
       true, 'Sale rates exactly as the chart holds them'
WHERE NOT EXISTS (SELECT 1 FROM app.scenario);

INSERT INTO app.scenario (code, name, method, target_pct, note)
SELECT 'VA100', 'Value added +100%', 'VALUE_ADDED', 100,
       'Stones and making together must double their cost. Metal passes through.'
WHERE NOT EXISTS (SELECT 1 FROM app.scenario WHERE code='VA100');

-- everyone sees the default; nobody but admin switches a piece, to begin with
INSERT INTO app.scenario_role (scenario_id, role_id, may_see, may_switch)
SELECT s.scenario_id, r.role_id, s.is_default, r.code = 'ADMIN'
  FROM app.scenario s CROSS JOIN app.role r
ON CONFLICT DO NOTHING;

-- ── what a scenario makes this piece worth ───────────────────────────────
CREATE OR REPLACE FUNCTION app.scenario_price(p_jc INTEGER, p_scenario INTEGER DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  s            app.scenario%ROWTYPE;
  v_ver        INT;
  v_karat      TEXT;
  v_metal_gm   NUMERIC := 0;
  v_metal_sale NUMERIC := 0;
  v_metal_cost NUMERIC := 0;
  v_making     NUMERIC := 0;
  v_making_c   NUMERIC := 0;
  v_stone_cost NUMERIC := 0;
  v_stone_wt   NUMERIC := 0;
  v_stone_chart NUMERIC := 0;
  v_stone_sale NUMERIC := 0;
  v_mult       NUMERIC;
  v_capped     TEXT := NULL;
BEGIN
  SELECT * INTO s FROM app.scenario
   WHERE scenario_id = COALESCE(p_scenario,
           (SELECT scenario_id FROM app.jewel_code WHERE jewel_code_id = p_jc),
           (SELECT scenario_id FROM app.scenario WHERE is_default));
  IF s.scenario_id IS NULL THEN RAISE EXCEPTION 'No pricing scenario is set up.'; END IF;

  SELECT current_bom_version, metal_purity INTO v_ver, v_karat
    FROM app.jewel_code WHERE jewel_code_id = p_jc;

  SELECT COALESCE(SUM(line_weight_gm(l.qty_value,l.qty_uom)),0) INTO v_metal_gm
    FROM app.jewel_material_line l JOIN app.material m USING (material_id)
   WHERE l.jewel_code_id=p_jc AND l.version_no=v_ver AND m.mat_class='METAL';

  v_metal_sale := ROUND(app.alloy_sale_rate(v_karat) * v_metal_gm);
  v_metal_cost := ROUND(app.alloy_cost_rate(v_karat) * v_metal_gm);

  -- making: whatever the line says, per gram or flat
  SELECT COALESCE(SUM(CASE
           WHEN l.basis='FLAT'  THEN COALESCE(l.sale_rate,0)
           WHEN l.basis='BY_PIECE' THEN COALESCE(l.sale_rate,0)*COALESCE(l.pcs,1)
           ELSE COALESCE(l.sale_rate,0) * v_metal_gm END),0),
         COALESCE(SUM(CASE
           WHEN l.basis='FLAT'  THEN COALESCE(l.cost_rate,0)
           WHEN l.basis='BY_PIECE' THEN COALESCE(l.cost_rate,0)*COALESCE(l.pcs,1)
           ELSE COALESCE(l.cost_rate,0) * v_metal_gm END),0)
    INTO v_making, v_making_c
    FROM app.jewel_material_line l JOIN app.material m USING (material_id)
   WHERE l.jewel_code_id=p_jc AND l.version_no=v_ver AND m.mat_class='LABOUR';

  -- everything that is not metal and not labour
  SELECT COALESCE(SUM(COALESCE(l.cost_rate,0)*COALESCE(l.qty_value,0)),0),
         COALESCE(SUM(COALESCE(l.qty_value,0)),0),
         COALESCE(SUM(COALESCE(
             app.chart_rate(m.item_code, COALESCE(l.size_band,''), 'SALE', s.chart_id),
             l.sale_rate, 0) * COALESCE(l.qty_value,0)),0)
    INTO v_stone_cost, v_stone_wt, v_stone_chart
    FROM app.jewel_material_line l JOIN app.material m USING (material_id)
   WHERE l.jewel_code_id=p_jc AND l.version_no=v_ver
     AND m.mat_class NOT IN ('METAL','LABOUR');

  IF s.method = 'CHART' THEN
    v_stone_sale := v_stone_chart;
  ELSE
    -- value added = everything except metal. Target a markup on THAT, and
    -- let the stones carry whatever is left after making.
    DECLARE v_va_cost NUMERIC := v_stone_cost + v_making_c;
            v_va_target NUMERIC;
    BEGIN
      v_va_target  := v_va_cost * (1 + s.target_pct/100.0);
      v_stone_sale := v_va_target - v_making;
      IF v_stone_cost > 0 THEN
        v_mult := v_stone_sale / v_stone_cost;
        IF v_mult < s.min_multiple THEN
          v_stone_sale := v_stone_cost * s.min_multiple;
          v_capped := 'floor';        -- making alone already exceeds the target
        ELSIF v_mult > s.max_multiple THEN
          v_stone_sale := v_stone_cost * s.max_multiple;
          v_capped := 'ceiling';      -- would price stones absurdly
        END IF;
      ELSIF v_stone_sale > 0 THEN
        v_stone_sale := 0;            -- nothing to carry it
        v_capped := 'no stones';
      END IF;
    END;
  END IF;

  RETURN jsonb_build_object(
    'scenario', s.code, 'scenario_name', s.name, 'method', s.method,
    'metal_gm', round(v_metal_gm,3),
    'metal_cost', v_metal_cost, 'metal_sale', v_metal_sale,
    'making_cost', round(v_making_c), 'making_sale', round(v_making),
    'stone_cost', round(v_stone_cost), 'stone_sale', round(v_stone_sale),
    'stone_multiple', CASE WHEN v_stone_cost>0
                           THEN round(v_stone_sale/v_stone_cost,2) END,
    'cost_today', v_metal_cost + round(v_making_c) + round(v_stone_cost),
    'price', v_metal_sale + round(v_making) + round(v_stone_sale),
    'capped', v_capped);
END $fn$;

COMMENT ON FUNCTION app.scenario_price(INTEGER,INTEGER) IS
  'Price this piece under one scenario. Metal always passes through at its '
  'live rate; making is whatever the line says; only stones move.';
;
