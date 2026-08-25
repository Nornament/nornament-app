
-- 0036b  Scenarios exposed, and the guard rails around switching one.
--
-- Deliberate: api.jewel.sale_price is NOT changed. It still comes from the
-- rates stored on the lines. A scenario is a comparison you opt into, not
-- something that silently reprices 214 pieces the moment it is created.

CREATE OR REPLACE VIEW api.scenario
WITH (security_invoker = false) AS
SELECT s.scenario_id, s.code, s.name, s.method, s.target_pct,
       s.spread_over, s.spread_by, s.min_multiple, s.max_multiple,
       s.is_default, s.is_active, s.note,
       c.name AS chart_name,
       COALESCE(sr.may_switch, false) AS i_may_switch
  FROM app.scenario s
  LEFT JOIN app.rate_chart c ON c.chart_id = s.chart_id
  LEFT JOIN app.scenario_role sr
         ON sr.scenario_id = s.scenario_id
        AND sr.role_id = (SELECT role_id FROM app.app_user WHERE user_id = app.current_user_id())
 WHERE s.is_active
   AND (app.is_admin() OR COALESCE(sr.may_see, false))
 ORDER BY s.is_default DESC, s.code;

GRANT SELECT ON api.scenario TO anon, authenticated;

-- every scenario priced against one piece, for the piece's Pricing tab
CREATE OR REPLACE FUNCTION app.piece_scenarios(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_code TEXT := upper(btrim(coalesce(p->>'jewel_code','')));
        v_jc INT; v_cur INT; v_out jsonb;
BEGIN
  IF NOT app.has_cap('sale') THEN
    RAISE EXCEPTION 'You do not have permission to see prices.';
  END IF;
  SELECT jewel_code_id, scenario_id INTO v_jc, v_cur
    FROM app.jewel_code WHERE upper(jewel_code) = v_code;
  IF v_jc IS NULL THEN RAISE EXCEPTION 'No piece called "%".', v_code; END IF;

  SELECT jsonb_agg(r ORDER BY r->>'code')
    INTO v_out
    FROM (
      SELECT app.scenario_price(v_jc, s.scenario_id)
             || jsonb_build_object(
                  'scenario_id', s.scenario_id,
                  'code', s.code,
                  'in_use', s.scenario_id = COALESCE(v_cur,
                              (SELECT scenario_id FROM app.scenario WHERE is_default)),
                  'may_switch', app.is_admin() OR COALESCE(sr.may_switch,false)) AS r
        FROM app.scenario s
        LEFT JOIN app.scenario_role sr
               ON sr.scenario_id = s.scenario_id
              AND sr.role_id = (SELECT role_id FROM app.app_user WHERE user_id = app.current_user_id())
       WHERE s.is_active AND (app.is_admin() OR COALESCE(sr.may_see,false))
    ) t;

  RETURN jsonb_build_object('ok', true, 'jewel_code', v_code,
    'stored_sale_price', app.live_sale_price(v_jc),
    'cost_frozen', (SELECT total_cost_price FROM app.bom_version
                     WHERE jewel_code_id=v_jc AND is_current),
    'cost_today', app.current_cost(v_jc),
    'scenarios', COALESCE(v_out,'[]'::jsonb));
END $fn$;

-- switching a piece onto a scenario
CREATE OR REPLACE FUNCTION app.set_piece_scenario(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_code TEXT := upper(btrim(coalesce(p->>'jewel_code','')));
        v_sid INT := nullif(p->>'scenario_id','')::int;
        v_jc INT; v_may BOOLEAN; v_name TEXT;
BEGIN
  SELECT jewel_code_id INTO v_jc FROM app.jewel_code WHERE upper(jewel_code)=v_code;
  IF v_jc IS NULL THEN RAISE EXCEPTION 'No piece called "%".', v_code; END IF;

  IF v_sid IS NULL THEN
    IF NOT app.is_admin() THEN RAISE EXCEPTION 'Only an admin can clear a piece''s scenario.'; END IF;
    UPDATE app.jewel_code SET scenario_id = NULL WHERE jewel_code_id = v_jc;
    PERFORM app.log('UPDATE','jewel_code', v_code, 'scenario cleared — back to the default');
    RETURN jsonb_build_object('ok',true,'jewel_code',v_code,'scenario',null);
  END IF;

  SELECT s.name, app.is_admin() OR COALESCE(sr.may_switch,false)
    INTO v_name, v_may
    FROM app.scenario s
    LEFT JOIN app.scenario_role sr ON sr.scenario_id=s.scenario_id
         AND sr.role_id=(SELECT role_id FROM app.app_user WHERE user_id=app.current_user_id())
   WHERE s.scenario_id = v_sid AND s.is_active;
  IF v_name IS NULL THEN RAISE EXCEPTION 'No such scenario.'; END IF;
  IF NOT v_may THEN
    RAISE EXCEPTION 'You may see that scenario but not put a piece on it. Ask an admin.';
  END IF;

  UPDATE app.jewel_code SET scenario_id = v_sid WHERE jewel_code_id = v_jc;
  PERFORM app.log('UPDATE','jewel_code', v_code, 'priced on scenario '||v_name);
  RETURN jsonb_build_object('ok',true,'jewel_code',v_code,'scenario',v_name,
                            'price',(app.scenario_price(v_jc,v_sid)->>'price')::numeric);
END $fn$;

CREATE OR REPLACE FUNCTION app.upsert_scenario(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_code TEXT := upper(btrim(coalesce(p->>'code','')));
        v_id INT; v_created BOOLEAN := false;
BEGIN
  IF NOT app.is_admin() THEN
    RAISE EXCEPTION 'Only an admin can create or change a pricing scenario.';
  END IF;
  IF v_code = '' THEN RAISE EXCEPTION 'A scenario needs a code.'; END IF;
  IF upper(coalesce(p->>'method','')) NOT IN ('CHART','VALUE_ADDED') THEN
    RAISE EXCEPTION 'Method must be CHART or VALUE_ADDED.';
  END IF;
  IF upper(p->>'method') = 'VALUE_ADDED' AND nullif(p->>'target_pct','') IS NULL THEN
    RAISE EXCEPTION 'A value-added scenario needs a target percentage.';
  END IF;

  SELECT scenario_id INTO v_id FROM app.scenario WHERE code = v_code;
  IF v_id IS NULL THEN
    v_created := true;
    INSERT INTO app.scenario (code,name,method,chart_id,target_pct,spread_by,
                              min_multiple,max_multiple,note)
    VALUES (v_code, coalesce(nullif(btrim(p->>'name'),''), v_code),
            upper(p->>'method'), nullif(p->>'chart_id','')::int,
            nullif(p->>'target_pct','')::numeric,
            coalesce(nullif(upper(p->>'spread_by'),''),'COST'),
            coalesce(nullif(p->>'min_multiple','')::numeric,1.0),
            coalesce(nullif(p->>'max_multiple','')::numeric,8.0),
            nullif(btrim(p->>'note'),''))
    RETURNING scenario_id INTO v_id;
    INSERT INTO app.scenario_role (scenario_id, role_id, may_see, may_switch)
    SELECT v_id, role_id, code='ADMIN', code='ADMIN' FROM app.role;
  ELSE
    UPDATE app.scenario
       SET name = coalesce(nullif(btrim(p->>'name'),''), name),
           method = upper(p->>'method'),
           chart_id = coalesce(nullif(p->>'chart_id','')::int, chart_id),
           target_pct = coalesce(nullif(p->>'target_pct','')::numeric, target_pct),
           spread_by = coalesce(nullif(upper(p->>'spread_by'),''), spread_by),
           min_multiple = coalesce(nullif(p->>'min_multiple','')::numeric, min_multiple),
           max_multiple = coalesce(nullif(p->>'max_multiple','')::numeric, max_multiple),
           note = coalesce(nullif(btrim(p->>'note'),''), note)
     WHERE scenario_id = v_id;
  END IF;
  PERFORM app.log(CASE WHEN v_created THEN 'INSERT' ELSE 'UPDATE' END,
                  'scenario', v_code, p->>'method');
  RETURN jsonb_build_object('ok',true,'scenario_id',v_id,'code',v_code,'created',v_created);
END $fn$;

CREATE OR REPLACE FUNCTION app.set_scenario_roles(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_id INT := nullif(p->>'scenario_id','')::int; r jsonb;
BEGIN
  IF NOT app.is_admin() THEN RAISE EXCEPTION 'Only an admin can change who may price.'; END IF;
  FOR r IN SELECT * FROM jsonb_array_elements(coalesce(p->'roles','[]'::jsonb)) LOOP
    INSERT INTO app.scenario_role (scenario_id, role_id, may_see, may_switch)
    SELECT v_id, ro.role_id,
           coalesce((r->>'may_see')::boolean,false),
           coalesce((r->>'may_switch')::boolean,false)
      FROM app.role ro WHERE ro.code = upper(r->>'role')
    ON CONFLICT (scenario_id, role_id) DO UPDATE
       SET may_see = EXCLUDED.may_see, may_switch = EXCLUDED.may_switch;
  END LOOP;
  PERFORM app.log('UPDATE','scenario_role', v_id::text, 'visibility changed');
  RETURN jsonb_build_object('ok',true,'scenario_id',v_id);
END $fn$;

CREATE OR REPLACE FUNCTION api.piece_scenarios(p jsonb) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$ SELECT app.piece_scenarios(p) $$;
CREATE OR REPLACE FUNCTION api.set_piece_scenario(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public AS $$ SELECT app.set_piece_scenario(p) $$;
CREATE OR REPLACE FUNCTION api.upsert_scenario(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public AS $$ SELECT app.upsert_scenario(p) $$;
CREATE OR REPLACE FUNCTION api.set_scenario_roles(p jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = app, public AS $$ SELECT app.set_scenario_roles(p) $$;

GRANT EXECUTE ON FUNCTION api.piece_scenarios(jsonb), api.set_piece_scenario(jsonb),
  api.upsert_scenario(jsonb), api.set_scenario_roles(jsonb) TO anon, authenticated;
REVOKE ALL ON FUNCTION app.piece_scenarios(jsonb), app.set_piece_scenario(jsonb),
  app.upsert_scenario(jsonb), app.set_scenario_roles(jsonb) FROM anon, authenticated;
;
