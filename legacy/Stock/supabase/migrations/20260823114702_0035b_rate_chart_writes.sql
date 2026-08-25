
-- 0035b  Editing charts, and the refresh button next to a BOM

CREATE OR REPLACE FUNCTION app.set_chart_rate(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_chart INT  := nullif(p->>'chart_id','')::int;
  v_mat   TEXT := upper(btrim(coalesce(p->>'material','')));
  v_band  TEXT := coalesce(btrim(coalesce(p->>'size_band','')),'');
  v_cost  NUMERIC := nullif(p->>'cost_rate','')::numeric;
  v_sale  NUMERIC := nullif(p->>'sale_rate','')::numeric;
  v_mid INT; v_locked BOOLEAN; v_cls app.material_class;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to change rates.';
  END IF;
  v_chart := COALESCE(v_chart, (SELECT chart_id FROM app.rate_chart WHERE is_default));
  SELECT is_locked INTO v_locked FROM app.rate_chart WHERE chart_id = v_chart;
  IF v_locked THEN
    RAISE EXCEPTION 'That chart has priced live stock and cannot be edited. Fork it first.';
  END IF;

  SELECT material_id, mat_class INTO v_mid, v_cls FROM app.material WHERE item_code = v_mat;
  IF v_mid IS NULL THEN RAISE EXCEPTION 'No material called "%".', v_mat; END IF;
  IF v_cls = 'METAL' THEN
    RAISE EXCEPTION 'Metal is priced from its live rate, not from a chart. Change it under Metal rates.';
  END IF;

  INSERT INTO app.rate_chart_line (chart_id, material_id, size_band, cost_rate, sale_rate)
  VALUES (v_chart, v_mid, v_band, v_cost, v_sale)
  ON CONFLICT (chart_id, material_id, size_band) DO UPDATE
     SET cost_rate = COALESCE(EXCLUDED.cost_rate, app.rate_chart_line.cost_rate),
         sale_rate = COALESCE(EXCLUDED.sale_rate, app.rate_chart_line.sale_rate);

  PERFORM app.log('UPDATE','rate_chart_line', v_mat||COALESCE(' '||nullif(v_band,''),''),
                  'cost '||COALESCE(v_cost::text,'—')||' / sale '||COALESCE(v_sale::text,'—'));
  RETURN jsonb_build_object('ok',true,'material',v_mat,'size_band',v_band,
                            'cost_rate',v_cost,'sale_rate',v_sale);
END $fn$;

CREATE OR REPLACE FUNCTION app.fork_chart(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_src INT := nullif(p->>'chart_id','')::int;
        v_name TEXT := btrim(coalesce(p->>'name',''));
        v_new INT; v_code TEXT; v_ver INT;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to create a rate chart.';
  END IF;
  v_src := COALESCE(v_src, (SELECT chart_id FROM app.rate_chart WHERE is_default));
  SELECT code INTO v_code FROM app.rate_chart WHERE chart_id = v_src;
  IF v_code IS NULL THEN RAISE EXCEPTION 'No chart to fork from.'; END IF;
  SELECT COALESCE(max(version_no),0)+1 INTO v_ver FROM app.rate_chart WHERE code = v_code;

  INSERT INTO app.rate_chart (code, name, version_no, forked_from, note, created_by)
  VALUES (v_code, COALESCE(nullif(v_name,''),
            (SELECT name FROM app.rate_chart WHERE chart_id=v_src)||' v'||v_ver),
          v_ver, v_src, 'Forked from version '||(SELECT version_no FROM app.rate_chart WHERE chart_id=v_src),
          app.current_user_id())
  RETURNING chart_id INTO v_new;

  INSERT INTO app.rate_chart_line (chart_id, material_id, size_band, cost_rate, sale_rate, rate_uom)
  SELECT v_new, material_id, size_band, cost_rate, sale_rate, rate_uom
    FROM app.rate_chart_line WHERE chart_id = v_src;

  PERFORM app.log('INSERT','rate_chart', v_code||' v'||v_ver, 'forked from chart '||v_src);
  RETURN jsonb_build_object('ok',true,'chart_id',v_new,'code',v_code,'version_no',v_ver);
END $fn$;

CREATE OR REPLACE FUNCTION app.set_default_chart(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_id INT := nullif(p->>'chart_id','')::int;
BEGIN
  IF NOT app.is_admin() THEN
    RAISE EXCEPTION 'Only an admin can change the default rate chart.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM app.rate_chart WHERE chart_id = v_id) THEN
    RAISE EXCEPTION 'No such chart.';
  END IF;
  UPDATE app.rate_chart SET is_default = false WHERE is_default;
  UPDATE app.rate_chart SET is_default = true WHERE chart_id = v_id;
  PERFORM app.log('UPDATE','rate_chart', v_id::text, 'made the default');
  RETURN jsonb_build_object('ok',true,'chart_id',v_id);
END $fn$;

-- ── the refresh button ───────────────────────────────────────────────────
-- Shows what WOULD change unless told to apply. Metal lines are never
-- touched: their rate is live and a chart has no business overriding it.
CREATE OR REPLACE FUNCTION app.refresh_bom_rates(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code  TEXT := upper(btrim(coalesce(p->>'jewel_code','')));
  v_chart INT  := nullif(p->>'chart_id','')::int;
  v_apply BOOLEAN := coalesce((p->>'apply')::boolean, false);
  v_jc INT; v_ver INT; v_rows jsonb; v_n INT := 0;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to reprice a piece.';
  END IF;
  v_chart := COALESCE(v_chart, (SELECT chart_id FROM app.rate_chart WHERE is_default));
  SELECT jewel_code_id, current_bom_version INTO v_jc, v_ver
    FROM app.jewel_code WHERE upper(jewel_code) = v_code;
  IF v_jc IS NULL THEN RAISE EXCEPTION 'No piece called "%".', v_code; END IF;

  SELECT jsonb_agg(jsonb_build_object(
           'line_no', t.line_no, 'material', t.item_code, 'size_band', t.size_band,
           'cost_now', t.cost_rate, 'cost_chart', t.c_cost,
           'sale_now', t.sale_rate, 'sale_chart', t.c_sale)), count(*)
    INTO v_rows, v_n
    FROM (
      SELECT l.line_no, m.item_code, COALESCE(l.size_band,'') AS size_band,
             l.cost_rate, l.sale_rate, cl.cost_rate AS c_cost, cl.sale_rate AS c_sale
        FROM app.jewel_material_line l
        JOIN app.material m USING (material_id)
        LEFT JOIN app.rate_chart_line cl
               ON cl.chart_id = v_chart AND cl.material_id = l.material_id
              AND cl.size_band = COALESCE(l.size_band,'')
       WHERE l.jewel_code_id = v_jc AND l.version_no = v_ver
         AND m.mat_class <> 'METAL'
         AND cl.chart_id IS NOT NULL
         AND (l.cost_rate IS DISTINCT FROM cl.cost_rate
           OR l.sale_rate IS DISTINCT FROM cl.sale_rate)
    ) t;

  IF v_apply AND v_n > 0 THEN
    UPDATE app.jewel_material_line l
       SET cost_rate = COALESCE(cl.cost_rate, l.cost_rate),
           sale_rate = COALESCE(cl.sale_rate, l.sale_rate),
           off_chart = false
      FROM app.rate_chart_line cl, app.material m
     WHERE m.material_id = l.material_id
       AND cl.chart_id = v_chart AND cl.material_id = l.material_id
       AND cl.size_band = COALESCE(l.size_band,'')
       AND l.jewel_code_id = v_jc AND l.version_no = v_ver
       AND m.mat_class <> 'METAL';
    PERFORM app.recost_jewel(v_jc);
    PERFORM app.log('UPDATE','jewel_material_line', v_code,
                    v_n||' line(s) refreshed from rate chart '||v_chart);
  END IF;

  RETURN jsonb_build_object('ok', true, 'jewel_code', v_code, 'chart_id', v_chart,
    'lines_differing', v_n, 'applied', v_apply, 'changes', COALESCE(v_rows,'[]'::jsonb),
    'note', CASE WHEN v_n = 0 THEN 'Every line already matches the chart.'
                 WHEN v_apply THEN v_n||' line(s) updated. Metal was not touched — it is priced live.'
                 ELSE 'Nothing changed yet. Send apply:true to write these.' END);
END $fn$;

CREATE OR REPLACE FUNCTION api.set_chart_rate(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public AS $$ SELECT app.set_chart_rate(p) $$;
CREATE OR REPLACE FUNCTION api.fork_chart(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public AS $$ SELECT app.fork_chart(p) $$;
CREATE OR REPLACE FUNCTION api.set_default_chart(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public AS $$ SELECT app.set_default_chart(p) $$;
CREATE OR REPLACE FUNCTION api.refresh_bom_rates(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public AS $$ SELECT app.refresh_bom_rates(p) $$;

GRANT EXECUTE ON FUNCTION api.set_chart_rate(jsonb), api.fork_chart(jsonb),
  api.set_default_chart(jsonb), api.refresh_bom_rates(jsonb) TO anon, authenticated;
REVOKE ALL ON FUNCTION app.set_chart_rate(jsonb), app.fork_chart(jsonb),
  app.set_default_chart(jsonb), app.refresh_bom_rates(jsonb) FROM anon, authenticated;
;
