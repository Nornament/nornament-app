
-- "in use" was marking the default scenario even when the piece is not on any
-- scenario at all — and its price is still the one stored on the lines. That
-- reads as though the app is quoting a figure it is not. A scenario is in use
-- only when the piece has actually been put on it.
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

  SELECT jsonb_agg(r ORDER BY r->>'code') INTO v_out
    FROM (
      SELECT app.scenario_price(v_jc, s.scenario_id)
             || jsonb_build_object(
                  'scenario_id', s.scenario_id,
                  'code', s.code,
                  'in_use', v_cur IS NOT NULL AND s.scenario_id = v_cur,
                  'is_default', s.is_default,
                  'may_switch', app.is_admin() OR COALESCE(sr.may_switch,false)) AS r
        FROM app.scenario s
        LEFT JOIN app.scenario_role sr
               ON sr.scenario_id = s.scenario_id
              AND sr.role_id = (SELECT role_id FROM app.app_user WHERE user_id = app.current_user_id())
       WHERE s.is_active AND (app.is_admin() OR COALESCE(sr.may_see,false))
    ) t;

  RETURN jsonb_build_object('ok', true, 'jewel_code', v_code,
    'on_scenario', v_cur IS NOT NULL,
    'stored_sale_price', app.live_sale_price(v_jc),
    'cost_frozen', (SELECT total_cost_price FROM app.bom_version
                     WHERE jewel_code_id=v_jc AND is_current),
    'cost_today', app.current_cost(v_jc),
    'scenarios', COALESCE(v_out,'[]'::jsonb));
END $fn$;
;
