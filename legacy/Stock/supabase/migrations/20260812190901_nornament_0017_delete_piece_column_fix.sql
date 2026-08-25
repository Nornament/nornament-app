-- the audit column is old_values, not old_value
CREATE OR REPLACE FUNCTION app.delete_piece(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code   TEXT := upper(btrim(p->>'jewel_code'));
  v_reason TEXT := NULLIF(btrim(COALESCE(p->>'reason','')),'');
  v_jc INT; v_state stock_state; v_sales INT; v_snap JSONB;
BEGIN
  IF NOT (app.is_admin() OR session_user IN ('postgres','supabase_admin')) THEN
    RAISE EXCEPTION 'Only an admin can delete a piece.';
  END IF;
  IF v_reason IS NULL THEN
    RAISE EXCEPTION 'A reason is required to delete %.', v_code;
  END IF;

  SELECT jewel_code_id, stock_state INTO v_jc, v_state
    FROM jewel_code WHERE upper(jewel_code) = v_code;
  IF v_jc IS NULL THEN RAISE EXCEPTION 'Jewel code % not found.', v_code; END IF;

  IF v_state IN ('SOLD','MELTED','LOST') THEN
    RAISE EXCEPTION 'Jewel code % is %. That record is the only evidence of what happened to the piece and cannot be deleted.', v_code, v_state;
  END IF;
  SELECT count(*) INTO v_sales FROM sale WHERE jewel_code_id = v_jc;
  IF v_sales > 0 THEN
    RAISE EXCEPTION 'Jewel code % has % sale record(s) against it. Reverse the sale first if it was entered in error.', v_code, v_sales;
  END IF;

  SELECT jsonb_build_object(
    'piece',     to_jsonb(j),
    'boms',      (SELECT jsonb_agg(to_jsonb(b)) FROM bom_version b WHERE b.jewel_code_id=v_jc),
    'lines',     (SELECT jsonb_agg(to_jsonb(l)) FROM jewel_material_line l WHERE l.jewel_code_id=v_jc),
    'movements', (SELECT jsonb_agg(to_jsonb(m)) FROM stock_movement m WHERE m.jewel_code_id=v_jc),
    'media',     (SELECT jsonb_agg(to_jsonb(x)) FROM media_asset x WHERE x.jewel_code_id=v_jc))
  INTO v_snap FROM jewel_code j WHERE j.jewel_code_id = v_jc;

  INSERT INTO activity_log (table_name, record_pk, action, user_id, detail, old_values)
  VALUES ('jewel_code', v_code, 'DELETE', app.current_user_id(),
          'Deleted. Reason: '||v_reason, v_snap);

  DELETE FROM jewel_material_line WHERE jewel_code_id = v_jc;
  DELETE FROM stock_movement      WHERE jewel_code_id = v_jc;
  DELETE FROM media_asset         WHERE jewel_code_id = v_jc;
  DELETE FROM bom_version         WHERE jewel_code_id = v_jc;
  DELETE FROM jewel_code          WHERE jewel_code_id = v_jc;

  RETURN jsonb_build_object('ok',true,'jewel_code',v_code,'deleted',true,
    'note','The full record is kept in the audit log and can be put back by hand.');
END $fn$;;
