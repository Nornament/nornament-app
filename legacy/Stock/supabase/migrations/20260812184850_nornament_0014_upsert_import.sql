-- ============================================================
-- 0014  The spreadsheet is the way stock gets in, and the same
--       sheet gets uploaded again later with more columns filled.
--
-- So an import must be safe to repeat. Rules:
--   * a jewel code that does not exist  -> created
--   * a jewel code that does exist      -> only BLANK fields are
--     filled from the sheet. A value already in the database is
--     never quietly replaced by the sheet.
--   * mode 'overwrite' is the explicit opt-out of that rule, and
--     it says in the report exactly what it changed.
--   * materials are only written if the piece has none. Replacing
--     an existing BOM forks a CORRECTION version, never edits.
-- ============================================================
SET search_path TO app, public;

CREATE OR REPLACE FUNCTION app.upsert_piece(p JSONB, p_mode TEXT DEFAULT 'fill')
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code  TEXT := upper(btrim(p->>'jewel_code'));
  v_jc    INT;
  v_over  BOOLEAN := (lower(COALESCE(p_mode,'fill')) = 'overwrite');
  v_patch JSONB := '{}'::jsonb;
  v_did   TEXT[] := '{}';
  v_lines JSONB := COALESCE(p->'lines','[]'::jsonb);
  v_has   INT;
  v_state stock_state;
  k       TEXT;
  v_map   CONSTANT JSONB := jsonb_build_object(
    'karat','metal_purity', 'colour','metal_colour', 'size','size_label',
    'quality','diamond_quality', 'gross_wt','measured_gross_wt_gm',
    'length_mm','length_mm', 'breadth_mm','breadth_mm', 'height_mm','height_mm',
    'huid','huid', 'hallmarked_on','hallmarked_on', 'hallmark_centre','hallmark_centre',
    'remarks','remarks');
  v_cur   TEXT;
BEGIN
  SELECT jewel_code_id, stock_state INTO v_jc, v_state
    FROM jewel_code WHERE upper(jewel_code) = v_code;

  ---- brand new piece: the existing path already does everything ----
  IF v_jc IS NULL THEN
    RETURN app.add_piece(p) || jsonb_build_object('action','added');
  END IF;

  IF v_state IN ('SOLD','MELTED','LOST') THEN
    RAISE EXCEPTION 'Jewel code % is %. Closed pieces are history and are not re-imported.',
      v_code, v_state;
  END IF;

  ---- existing piece: fill the blanks ----
  FOR k IN SELECT jsonb_object_keys(v_map) LOOP
    CONTINUE WHEN NOT (p ? k) OR COALESCE(p->>k,'') = '';
    EXECUTE format('SELECT %I::text FROM jewel_code WHERE jewel_code_id=$1', v_map->>k)
      INTO v_cur USING v_jc;
    IF v_cur IS NULL OR v_over THEN
      IF v_cur IS NOT NULL AND v_cur <> (p->>k) THEN
        v_did := v_did || (k || ': ' || v_cur || ' -> ' || (p->>k));
      ELSIF v_cur IS NULL THEN
        v_did := v_did || k;
      END IF;
      v_patch := v_patch || jsonb_build_object(k, p->>k);
    END IF;
  END LOOP;

  IF v_patch <> '{}'::jsonb THEN
    PERFORM app.update_piece(v_patch || jsonb_build_object('jewel_code', v_code));
  END IF;

  ---- materials ----
  IF jsonb_array_length(v_lines) > 0 THEN
    SELECT count(*) INTO v_has FROM jewel_material_line l JOIN jewel_code j USING (jewel_code_id)
     WHERE l.jewel_code_id = v_jc AND l.version_no = j.current_bom_version;
    IF v_has = 0 THEN
      PERFORM app.set_bom(jsonb_build_object('jewel_code', v_code, 'lines', v_lines));
      v_did := v_did || ('materials (' || jsonb_array_length(v_lines) || ' lines)');
    ELSIF v_over THEN
      PERFORM app.set_bom(jsonb_build_object('jewel_code', v_code, 'lines', v_lines,
                                             'note','Replaced from spreadsheet upload'));
      v_did := v_did || 'materials replaced, new BOM version';
    END IF;
  END IF;

  ---- receipt ----
  IF COALESCE(p->>'location','') <> '' AND v_state = 'NOT_RECEIVED' THEN
    PERFORM app.receive_piece(jsonb_build_object('jewel_code', v_code,
              'location', p->>'location', 'date', NULLIF(p->>'received_on','')));
    v_did := v_did || ('received into ' || upper(p->>'location'));
  END IF;

  RETURN app.piece_state(v_jc)
       || jsonb_build_object('action', CASE WHEN array_length(v_did,1) IS NULL
                                            THEN 'unchanged' ELSE 'filled' END,
                             'changed', to_jsonb(v_did));
END $fn$;

DROP FUNCTION IF EXISTS app.import_pieces(JSONB);
CREATE OR REPLACE FUNCTION app.import_pieces(p JSONB, p_mode TEXT DEFAULT 'fill')
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  it JSONB; res JSONB; out JSONB := '[]'::jsonb;
  n_add INT := 0; n_fill INT := 0; n_same INT := 0; n_bad INT := 0;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to import stock.';
  END IF;
  IF jsonb_typeof(p) <> 'array' THEN
    RAISE EXCEPTION 'The import expects a list of pieces.';
  END IF;
  FOR it IN SELECT jsonb_array_elements(p) LOOP
    BEGIN
      res := app.upsert_piece(it, p_mode);
      CASE res->>'action'
        WHEN 'added'  THEN n_add  := n_add + 1;
        WHEN 'filled' THEN n_fill := n_fill + 1;
        ELSE               n_same := n_same + 1;
      END CASE;
    EXCEPTION WHEN OTHERS THEN
      res := jsonb_build_object('ok', false, 'action','rejected',
               'jewel_code', upper(COALESCE(it->>'jewel_code','(blank)')),
               'error', SQLERRM);
      n_bad := n_bad + 1;
    END;
    out := out || jsonb_build_array(res);
  END LOOP;
  PERFORM app.log('IMPORT','jewel_code','batch',
    n_add||' added, '||n_fill||' filled in, '||n_same||' unchanged, '||n_bad||' rejected',
    NULL, n_add + n_fill);
  RETURN jsonb_build_object('added',n_add,'filled',n_fill,'unchanged',n_same,
                            'rejected',n_bad,'rows',out);
END $fn$;

GRANT EXECUTE ON FUNCTION app.upsert_piece(JSONB,TEXT), app.import_pieces(JSONB,TEXT)
  TO authenticated;

DROP FUNCTION IF EXISTS api.import_pieces(JSONB);
CREATE OR REPLACE FUNCTION api.import_pieces(p JSONB, p_mode TEXT DEFAULT 'fill')
RETURNS JSONB LANGUAGE sql SECURITY INVOKER SET search_path = api, app, public
AS $$ SELECT app.import_pieces(p, p_mode) $$;
GRANT EXECUTE ON FUNCTION api.import_pieces(JSONB,TEXT) TO authenticated;;
