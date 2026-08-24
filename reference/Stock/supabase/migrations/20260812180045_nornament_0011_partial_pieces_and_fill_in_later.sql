-- ============================================================
-- 0011  A piece can now be created from what you actually know
--       on day one, and completed later.
--
-- The old add_piece demanded a full job card. That was wrong:
-- in practice about 40% is known at entry and the rest arrives
-- over the following days. A piece with gaps is now legal - it
-- just cannot enter stock until the gaps that matter are filled.
-- ============================================================
SET search_path TO app, public;

-- What is still missing on this piece, in plain words.
CREATE OR REPLACE FUNCTION app.piece_gaps(p_jc INT)
RETURNS TEXT[] LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT ARRAY(
    SELECT g FROM (
      SELECT 'Karat' AS g, 1 AS o WHERE (SELECT metal_purity FROM jewel_code WHERE jewel_code_id=p_jc) IS NULL
      UNION ALL
      SELECT 'Gross weight', 2 WHERE (SELECT measured_gross_wt_gm FROM jewel_code WHERE jewel_code_id=p_jc) IS NULL
      UNION ALL
      SELECT 'Materials (BOM)', 3 WHERE NOT EXISTS (
        SELECT 1 FROM jewel_material_line l JOIN jewel_code j USING (jewel_code_id)
         WHERE l.jewel_code_id=p_jc AND l.version_no=j.current_bom_version)
      UNION ALL
      SELECT 'Rates on '||count(*)||' material line(s)', 4
        FROM jewel_material_line l JOIN jewel_code j USING (jewel_code_id)
       WHERE l.jewel_code_id=p_jc AND l.version_no=j.current_bom_version AND l.cost_rate IS NULL
       HAVING count(*) > 0
      UNION ALL
      SELECT 'Not received into any location', 5
        WHERE (SELECT stock_state FROM jewel_code WHERE jewel_code_id=p_jc) = 'NOT_RECEIVED'
      UNION ALL
      SELECT 'Photograph', 6 WHERE NOT EXISTS (
        SELECT 1 FROM media_asset WHERE jewel_code_id=p_jc AND kind='PHOTO')
    ) x ORDER BY o);
$$;
GRANT EXECUTE ON FUNCTION app.piece_gaps(INT) TO authenticated;

-- add_piece, relaxed: lines are optional, karat is optional.
CREATE OR REPLACE FUNCTION app.add_piece(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code   TEXT := upper(btrim(p->>'jewel_code'));
  v_style  TEXT := upper(btrim(COALESCE(NULLIF(p->>'style_code',''), p->>'jewel_code')));
  v_karat  TEXT := upper(btrim(COALESCE(p->>'karat','')));
  v_cat_id INT; v_style_id INT; v_loc_id INT; v_ven_id INT; v_jc INT;
  v_user   INT := app.current_user_id();
  v_on     DATE := COALESCE(NULLIF(p->>'received_on','')::date, CURRENT_DATE);
  v_lines  JSONB := COALESCE(p->'lines','[]'::jsonb);
  v_no     INT := 0;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to add stock.';
  END IF;
  IF COALESCE(v_code,'') = '' THEN
    RAISE EXCEPTION 'Jewel code is blank. It is the one field that cannot wait.';
  END IF;
  IF EXISTS (SELECT 1 FROM jewel_code WHERE upper(jewel_code) = v_code) THEN
    RAISE EXCEPTION 'Jewel code % already exists. One piece per jewel code - use a new code.', v_code;
  END IF;
  IF v_karat <> '' AND NOT EXISTS (SELECT 1 FROM metal_purity WHERE karat = v_karat) THEN
    RAISE EXCEPTION 'Karat "%" is not set up. Known: %', v_karat,
      (SELECT string_agg(karat,', ' ORDER BY karat) FROM metal_purity);
  END IF;

  IF COALESCE(p->>'location','') <> '' THEN
    SELECT location_id INTO v_loc_id FROM location
     WHERE upper(code)=upper(btrim(p->>'location')) OR upper(name)=upper(btrim(p->>'location'));
    IF v_loc_id IS NULL THEN
      RAISE EXCEPTION 'Location "%" not found. Known: %', p->>'location',
        (SELECT string_agg(code,', ' ORDER BY code) FROM location WHERE is_active);
    END IF;
  END IF;
  IF COALESCE(p->>'vendor','') <> '' THEN
    SELECT vendor_id INTO v_ven_id FROM vendor
     WHERE upper(code)=upper(btrim(p->>'vendor')) OR upper(name)=upper(btrim(p->>'vendor'));
    IF v_ven_id IS NULL THEN
      RAISE EXCEPTION 'Vendor "%" not found. Add it in Settings first.', p->>'vendor';
    END IF;
  END IF;

  SELECT style_id INTO v_style_id FROM style WHERE upper(style_code)=v_style;
  IF v_style_id IS NULL THEN
    SELECT category_id INTO v_cat_id FROM category
     WHERE upper(code)=upper(btrim(COALESCE(p->>'category','')))
        OR upper(name)=upper(btrim(COALESCE(p->>'category','')));
    IF v_cat_id IS NULL AND COALESCE(p->>'category','') <> '' THEN
      RAISE EXCEPTION 'Category "%" not found. Known: %', p->>'category',
        (SELECT string_agg(name,', ' ORDER BY sort_order) FROM category);
    END IF;
    IF v_cat_id IS NULL THEN
      RAISE EXCEPTION 'Design % is new, so it needs a category. Everything else can wait.', v_style;
    END IF;
    INSERT INTO style (style_code, name, category_id, state, nos_min_qty, created_by)
    VALUES (v_style, NULLIF(btrim(COALESCE(p->>'design_name','')),''), v_cat_id,
            'IN_STOCK_DESIGN', COALESCE(NULLIF(p->>'nos_min_qty','')::int,0), v_user)
    RETURNING style_id INTO v_style_id;
  END IF;

  INSERT INTO jewel_code (jewel_code, style_id, metal_purity, metal_colour, size_label,
                          diamond_quality, measured_gross_wt_gm, length_mm, breadth_mm, height_mm,
                          huid, hallmarked_on, hallmark_centre, vendor_id, remarks,
                          stock_state, current_bom_version, created_by)
  VALUES (v_code, v_style_id, NULLIF(v_karat,''), NULLIF(btrim(COALESCE(p->>'colour','')),''),
          NULLIF(btrim(COALESCE(p->>'size','')),''), NULLIF(btrim(COALESCE(p->>'quality','')),''),
          NULLIF(p->>'gross_wt','')::numeric, NULLIF(p->>'length_mm','')::numeric,
          NULLIF(p->>'breadth_mm','')::numeric, NULLIF(p->>'height_mm','')::numeric,
          NULLIF(btrim(COALESCE(p->>'huid','')),''), NULLIF(p->>'hallmarked_on','')::date,
          NULLIF(btrim(COALESCE(p->>'hallmark_centre','')),''), v_ven_id,
          NULLIF(btrim(COALESCE(p->>'remarks','')),''),
          'NOT_RECEIVED', 1, v_user)
  RETURNING jewel_code_id INTO v_jc;

  INSERT INTO bom_version (jewel_code_id, version_no, reason, note, is_current, created_by)
  VALUES (v_jc, 1, 'INITIAL', NULLIF(btrim(COALESCE(p->>'bom_note','')),''), TRUE, v_user);

  IF jsonb_array_length(v_lines) > 0 THEN
    v_no := app.write_bom_lines(v_jc, 1, v_lines, v_karat, v_on);
  END IF;
  PERFORM app.recost_jewel(v_jc, 1, v_user);

  IF v_loc_id IS NOT NULL THEN
    INSERT INTO stock_movement (jewel_code_id, move_type, to_location_id, resulting_state,
                                moved_at, reference_no, reason, user_id)
    VALUES (v_jc,'RECEIPT',v_loc_id,'IN_STOCK', v_on::timestamptz,
            NULLIF(btrim(COALESCE(p->>'reference_no','')),''),'Opening entry', v_user);
  END IF;

  PERFORM app.log('INSERT','jewel_code',v_code,'Piece added with '||v_no||' BOM lines',NULL,v_no);
  RETURN app.piece_state(v_jc);
END $fn$;

-- Shared line writer, used by add_piece and set_bom.
CREATE OR REPLACE FUNCTION app.write_bom_lines(p_jc INT, p_ver INT, p_lines JSONB,
                                               p_karat TEXT, p_on DATE)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  ln JSONB; v_no INT := 0; v_mat INT; v_class material_class;
  v_uom uom; v_basis charge_basis; v_cost NUMERIC; v_sale NUMERIC;
BEGIN
  FOR ln IN SELECT jsonb_array_elements(p_lines) LOOP
    v_no := v_no + 1;
    SELECT material_id, mat_class, default_uom INTO v_mat, v_class, v_uom
      FROM material WHERE upper(item_code)=upper(btrim(ln->>'material')) AND is_active;
    IF v_mat IS NULL THEN
      RAISE EXCEPTION 'Line %: material code "%" is not in your material master.',
        v_no, ln->>'material';
    END IF;
    IF COALESCE(ln->>'uom','') <> '' THEN v_uom := (upper(btrim(ln->>'uom')))::uom; END IF;
    v_basis := COALESCE(NULLIF(upper(btrim(COALESCE(ln->>'basis',''))),''),'BY_QTY')::charge_basis;
    IF v_class='LABOUR' AND NULLIF(ln->>'qty','') IS NULL AND v_basis='BY_QTY' THEN
      v_basis := 'BY_NET_METAL_WT';
    END IF;
    v_cost := COALESCE(NULLIF(ln->>'cost_rate','')::numeric,
                       app.rate_for(v_mat, COALESCE(ln->>'size_band',''), 'COST', p_on));
    IF v_class='METAL' AND COALESCE(p_karat,'') <> '' THEN
      v_sale := app.alloy_sale_rate(p_karat);
    ELSE
      v_sale := COALESCE(NULLIF(ln->>'sale_rate','')::numeric,
                         app.rate_for(v_mat, COALESCE(ln->>'size_band',''), 'SALE', p_on));
    END IF;
    INSERT INTO jewel_material_line (jewel_code_id, version_no, line_no, material_id, size_band,
                                     pcs, qty_value, qty_uom, basis, cost_rate, sale_rate, remarks)
    VALUES (p_jc, p_ver, v_no, v_mat, COALESCE(ln->>'size_band',''),
            NULLIF(ln->>'pcs','')::int, NULLIF(ln->>'qty','')::numeric, v_uom, v_basis,
            v_cost, v_sale, NULLIF(btrim(COALESCE(ln->>'remarks','')),''));
  END LOOP;
  RETURN v_no;
END $fn$;

-- One consistent answer to "where is this piece up to".
CREATE OR REPLACE FUNCTION app.piece_state(p_jc INT)
RETURNS JSONB LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT jsonb_build_object(
    'ok', true,
    'jewel_code', j.jewel_code, 'jewel_code_id', j.jewel_code_id,
    'stock_state', j.stock_state::text,
    'bom_version', j.current_bom_version,
    'lines', (SELECT count(*) FROM jewel_material_line
               WHERE jewel_code_id=p_jc AND version_no=j.current_bom_version),
    'bom_weight_gm', b.bom_weight_gm, 'net_metal_wt_gm', b.net_metal_wt_gm,
    'cost_price', b.total_cost_price,
    'sale_price', app.live_sale_price(p_jc),
    'missing', to_jsonb(app.piece_gaps(p_jc)))
  FROM jewel_code j
  LEFT JOIN bom_version b ON b.jewel_code_id=j.jewel_code_id AND b.is_current
  WHERE j.jewel_code_id = p_jc;
$$;
GRANT EXECUTE ON FUNCTION app.piece_state(INT) TO authenticated;

-- Fill in the 60% later. Only the keys you send are touched; anything you
-- leave out keeps its current value. Sending "" clears a field.
CREATE OR REPLACE FUNCTION app.update_piece(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code TEXT := upper(btrim(p->>'jewel_code'));
  v_jc INT; v_ven INT; v_changed TEXT := '';
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to change a piece.';
  END IF;
  SELECT jewel_code_id INTO v_jc FROM jewel_code WHERE upper(jewel_code)=v_code;
  IF v_jc IS NULL THEN RAISE EXCEPTION 'Jewel code % not found.', v_code; END IF;
  IF (SELECT stock_state FROM jewel_code WHERE jewel_code_id=v_jc)
       IN ('SOLD','MELTED','LOST') THEN
    RAISE EXCEPTION 'Jewel code % is closed. Its record is history now and cannot be edited.', v_code;
  END IF;
  IF p ? 'karat' AND COALESCE(p->>'karat','') <> ''
     AND NOT EXISTS (SELECT 1 FROM metal_purity WHERE karat=upper(btrim(p->>'karat'))) THEN
    RAISE EXCEPTION 'Karat "%" is not set up.', p->>'karat';
  END IF;
  IF p ? 'vendor' AND COALESCE(p->>'vendor','') <> '' THEN
    SELECT vendor_id INTO v_ven FROM vendor
     WHERE upper(code)=upper(btrim(p->>'vendor')) OR upper(name)=upper(btrim(p->>'vendor'));
    IF v_ven IS NULL THEN RAISE EXCEPTION 'Vendor "%" not found.', p->>'vendor'; END IF;
  END IF;

  UPDATE jewel_code SET
    metal_purity         = CASE WHEN p ? 'karat'       THEN NULLIF(upper(btrim(p->>'karat')),'') ELSE metal_purity END,
    metal_colour         = CASE WHEN p ? 'colour'      THEN NULLIF(btrim(p->>'colour'),'')       ELSE metal_colour END,
    size_label           = CASE WHEN p ? 'size'        THEN NULLIF(btrim(p->>'size'),'')         ELSE size_label END,
    diamond_quality      = CASE WHEN p ? 'quality'     THEN NULLIF(btrim(p->>'quality'),'')      ELSE diamond_quality END,
    measured_gross_wt_gm = CASE WHEN p ? 'gross_wt'    THEN NULLIF(p->>'gross_wt','')::numeric   ELSE measured_gross_wt_gm END,
    length_mm            = CASE WHEN p ? 'length_mm'   THEN NULLIF(p->>'length_mm','')::numeric  ELSE length_mm END,
    breadth_mm           = CASE WHEN p ? 'breadth_mm'  THEN NULLIF(p->>'breadth_mm','')::numeric ELSE breadth_mm END,
    height_mm            = CASE WHEN p ? 'height_mm'   THEN NULLIF(p->>'height_mm','')::numeric  ELSE height_mm END,
    huid                 = CASE WHEN p ? 'huid'        THEN NULLIF(btrim(p->>'huid'),'')         ELSE huid END,
    hallmarked_on        = CASE WHEN p ? 'hallmarked_on' THEN NULLIF(p->>'hallmarked_on','')::date ELSE hallmarked_on END,
    hallmark_centre      = CASE WHEN p ? 'hallmark_centre' THEN NULLIF(btrim(p->>'hallmark_centre'),'') ELSE hallmark_centre END,
    remarks              = CASE WHEN p ? 'remarks'     THEN NULLIF(btrim(p->>'remarks'),'')      ELSE remarks END,
    vendor_id            = CASE WHEN p ? 'vendor'      THEN v_ven                                ELSE vendor_id END,
    on_website           = CASE WHEN p ? 'on_website'  THEN (p->>'on_website')::boolean          ELSE on_website END,
    website_url          = CASE WHEN p ? 'website_url' THEN NULLIF(btrim(p->>'website_url'),'')  ELSE website_url END,
    updated_at           = now()
  WHERE jewel_code_id = v_jc;

  -- karat drives the gold sale rate, so a karat change must re-price the piece
  IF p ? 'karat' THEN
    UPDATE jewel_material_line l SET sale_rate = app.alloy_sale_rate(
             (SELECT metal_purity FROM jewel_code WHERE jewel_code_id=v_jc))
      FROM material m
     WHERE m.material_id=l.material_id AND m.mat_class='METAL'
       AND l.jewel_code_id=v_jc
       AND l.version_no=(SELECT current_bom_version FROM jewel_code WHERE jewel_code_id=v_jc);
  END IF;
  PERFORM app.recost_jewel(v_jc, NULL, app.current_user_id());

  SELECT string_agg(k,', ' ORDER BY k) INTO v_changed
    FROM jsonb_object_keys(p) k WHERE k <> 'jewel_code';
  PERFORM app.log('UPDATE','jewel_code',v_code,'Filled in: '||COALESCE(v_changed,'nothing'));
  RETURN app.piece_state(v_jc);
END $fn$;

-- Add or replace the material list. If the current version has no lines yet
-- this fills it in place. If it already has lines, a new CORRECTION version is
-- forked so the original is never lost.
CREATE OR REPLACE FUNCTION app.set_bom(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code TEXT := upper(btrim(p->>'jewel_code'));
  v_jc INT; v_cur INT; v_has INT; v_new INT; v_karat TEXT;
  v_user INT := app.current_user_id();
  v_lines JSONB := COALESCE(p->'lines','[]'::jsonb);
  v_n INT;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to change the bill of materials.';
  END IF;
  SELECT jewel_code_id, current_bom_version, metal_purity INTO v_jc, v_cur, v_karat
    FROM jewel_code WHERE upper(jewel_code)=v_code;
  IF v_jc IS NULL THEN RAISE EXCEPTION 'Jewel code % not found.', v_code; END IF;
  IF jsonb_array_length(v_lines)=0 THEN
    RAISE EXCEPTION 'No material lines sent. To leave the BOM empty, just do nothing.';
  END IF;

  SELECT count(*) INTO v_has FROM jewel_material_line
   WHERE jewel_code_id=v_jc AND version_no=v_cur;

  IF v_has = 0 THEN
    v_new := v_cur;                                   -- still the first draft
  ELSE
    SELECT max(version_no)+1 INTO v_new FROM bom_version WHERE jewel_code_id=v_jc;
    UPDATE bom_version SET is_current=FALSE WHERE jewel_code_id=v_jc AND is_current;
    INSERT INTO bom_version (jewel_code_id, version_no, reason, note, is_current, created_by)
    VALUES (v_jc, v_new, 'CORRECTION',
            NULLIF(btrim(COALESCE(p->>'note','')),''), TRUE, v_user);
    UPDATE jewel_code SET current_bom_version=v_new, updated_at=now() WHERE jewel_code_id=v_jc;
  END IF;

  v_n := app.write_bom_lines(v_jc, v_new, v_lines, v_karat, CURRENT_DATE);
  PERFORM app.recost_jewel(v_jc, v_new, v_user);
  PERFORM app.log('UPDATE','bom_version', v_code,
                  CASE WHEN v_has=0 THEN 'BOM filled in ('||v_n||' lines)'
                       ELSE 'BOM corrected, version '||v_new||' ('||v_n||' lines)' END,
                  NULL, v_n);
  RETURN app.piece_state(v_jc);
END $fn$;

-- Receive it into a location when it physically turns up. This is what puts
-- it in stock; before this it is only a record.
CREATE OR REPLACE FUNCTION app.receive_piece(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code TEXT := upper(btrim(p->>'jewel_code'));
  v_jc INT; v_loc INT; v_state stock_state;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to receive stock.';
  END IF;
  SELECT jewel_code_id, stock_state INTO v_jc, v_state
    FROM jewel_code WHERE upper(jewel_code)=v_code;
  IF v_jc IS NULL THEN RAISE EXCEPTION 'Jewel code % not found.', v_code; END IF;
  IF v_state <> 'NOT_RECEIVED' THEN
    RAISE EXCEPTION 'Jewel code % is already %. Use a transfer, not a receipt.', v_code, v_state;
  END IF;
  SELECT location_id INTO v_loc FROM location
   WHERE upper(code)=upper(btrim(COALESCE(p->>'location','')))
      OR upper(name)=upper(btrim(COALESCE(p->>'location','')));
  IF v_loc IS NULL THEN
    RAISE EXCEPTION 'Location "%" not found. Known: %', p->>'location',
      (SELECT string_agg(code,', ' ORDER BY code) FROM location WHERE is_active);
  END IF;
  INSERT INTO stock_movement (jewel_code_id, move_type, to_location_id, resulting_state,
                              moved_at, reference_no, reason, user_id)
  VALUES (v_jc,'RECEIPT',v_loc,'IN_STOCK',
          COALESCE(NULLIF(p->>'date','')::date, CURRENT_DATE)::timestamptz,
          NULLIF(btrim(COALESCE(p->>'reference_no','')),''),
          COALESCE(NULLIF(btrim(COALESCE(p->>'reason','')),''),'Received'), app.current_user_id());
  PERFORM app.log('UPDATE','stock_movement',v_code,'Received into '||(p->>'location'));
  RETURN app.piece_state(v_jc);
END $fn$;

GRANT EXECUTE ON FUNCTION app.write_bom_lines(INT,INT,JSONB,TEXT,DATE),
  app.update_piece(JSONB), app.set_bom(JSONB), app.receive_piece(JSONB) TO authenticated;

CREATE OR REPLACE FUNCTION api.update_piece(p JSONB) RETURNS JSONB
LANGUAGE sql SECURITY INVOKER SET search_path = api, app, public AS $$ SELECT app.update_piece(p) $$;
CREATE OR REPLACE FUNCTION api.set_bom(p JSONB) RETURNS JSONB
LANGUAGE sql SECURITY INVOKER SET search_path = api, app, public AS $$ SELECT app.set_bom(p) $$;
CREATE OR REPLACE FUNCTION api.receive_piece(p JSONB) RETURNS JSONB
LANGUAGE sql SECURITY INVOKER SET search_path = api, app, public AS $$ SELECT app.receive_piece(p) $$;
GRANT EXECUTE ON FUNCTION api.update_piece(JSONB), api.set_bom(JSONB),
  api.receive_piece(JSONB) TO authenticated;;
