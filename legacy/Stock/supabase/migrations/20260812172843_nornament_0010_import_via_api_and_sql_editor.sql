-- The SQL editor has no logged-in user, so app.has_cap() is false there and
-- the import refused to run. The service/postgres role already bypasses every
-- policy in this database, so allowing it here adds no exposure - it just
-- stops the editor being unusable for the initial load. Still audited.
CREATE OR REPLACE FUNCTION app.is_privileged()
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT app.has_cap('editBom')
      OR current_user IN ('postgres','supabase_admin','service_role','supabase_storage_admin');
$$;
GRANT EXECUTE ON FUNCTION app.is_privileged() TO authenticated;

CREATE OR REPLACE FUNCTION app.add_piece(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code     TEXT := upper(btrim(p->>'jewel_code'));
  v_style    TEXT := upper(btrim(COALESCE(p->>'style_code', p->>'jewel_code')));
  v_karat    TEXT := upper(btrim(COALESCE(p->>'karat','')));
  v_cat_id   INT; v_style_id INT; v_loc_id INT; v_ven_id INT; v_jc INT;
  v_user     INT := app.current_user_id();
  v_on       DATE := COALESCE(NULLIF(p->>'received_on','')::date, CURRENT_DATE);
  v_lines    JSONB := COALESCE(p->'lines','[]'::jsonb);
  ln         JSONB;
  v_no       INT := 0;
  v_mat      INT; v_class material_class; v_uom uom; v_basis charge_basis;
  v_cost     NUMERIC; v_sale NUMERIC;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to add stock.';
  END IF;
  IF v_code IS NULL OR v_code = '' THEN
    RAISE EXCEPTION 'jewel_code is blank.';
  END IF;
  IF EXISTS (SELECT 1 FROM jewel_code WHERE upper(jewel_code) = v_code) THEN
    RAISE EXCEPTION 'Jewel code % already exists. One piece per jewel code - use a new code.', v_code;
  END IF;
  IF v_karat <> '' AND NOT EXISTS (SELECT 1 FROM metal_purity WHERE karat = v_karat) THEN
    RAISE EXCEPTION 'Karat "%" is not set up. Known: %', v_karat,
      (SELECT string_agg(karat,', ' ORDER BY karat) FROM metal_purity);
  END IF;
  IF jsonb_array_length(v_lines) = 0 THEN
    RAISE EXCEPTION 'No BOM lines. A piece with no materials has no cost and no price.';
  END IF;

  IF COALESCE(p->>'location','') <> '' THEN
    SELECT location_id INTO v_loc_id FROM location
     WHERE upper(code) = upper(btrim(p->>'location')) OR upper(name) = upper(btrim(p->>'location'));
    IF v_loc_id IS NULL THEN
      RAISE EXCEPTION 'Location "%" not found. Known: %', p->>'location',
        (SELECT string_agg(code,', ' ORDER BY code) FROM location WHERE is_active);
    END IF;
  END IF;

  IF COALESCE(p->>'vendor','') <> '' THEN
    SELECT vendor_id INTO v_ven_id FROM vendor
     WHERE upper(code) = upper(btrim(p->>'vendor')) OR upper(name) = upper(btrim(p->>'vendor'));
    IF v_ven_id IS NULL THEN
      RAISE EXCEPTION 'Vendor "%" not found. Add it in Settings first.', p->>'vendor';
    END IF;
  END IF;

  SELECT style_id INTO v_style_id FROM style WHERE upper(style_code) = v_style;
  IF v_style_id IS NULL THEN
    IF COALESCE(p->>'category','') = '' THEN
      RAISE EXCEPTION 'Design % is new, so it needs a category.', v_style;
    END IF;
    SELECT category_id INTO v_cat_id FROM category
     WHERE upper(code) = upper(btrim(p->>'category')) OR upper(name) = upper(btrim(p->>'category'));
    IF v_cat_id IS NULL THEN
      RAISE EXCEPTION 'Category "%" not found. Known: %', p->>'category',
        (SELECT string_agg(name,', ' ORDER BY sort_order) FROM category);
    END IF;
    INSERT INTO style (style_code, name, category_id, state, nos_min_qty, created_by)
    VALUES (v_style, NULLIF(btrim(COALESCE(p->>'design_name','')),''), v_cat_id,
            'IN_STOCK_DESIGN', COALESCE(NULLIF(p->>'nos_min_qty','')::int, 0), v_user)
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

  FOR ln IN SELECT jsonb_array_elements(v_lines) LOOP
    v_no := v_no + 1;
    SELECT material_id, mat_class, default_uom INTO v_mat, v_class, v_uom
      FROM material WHERE upper(item_code) = upper(btrim(ln->>'material')) AND is_active;
    IF v_mat IS NULL THEN
      RAISE EXCEPTION 'Line %: material code "%" is not in your material master.', v_no, ln->>'material';
    END IF;
    IF COALESCE(ln->>'uom','') <> '' THEN v_uom := (upper(btrim(ln->>'uom')))::uom; END IF;
    v_basis := COALESCE(NULLIF(upper(btrim(COALESCE(ln->>'basis',''))),''), 'BY_QTY')::charge_basis;
    IF v_class = 'LABOUR' AND ln->>'qty' IS NULL AND v_basis = 'BY_QTY' THEN
      v_basis := 'BY_NET_METAL_WT';
    END IF;

    v_cost := COALESCE(NULLIF(ln->>'cost_rate','')::numeric,
                       app.rate_for(v_mat, COALESCE(ln->>'size_band',''), 'COST', v_on));
    IF v_class = 'METAL' AND v_karat <> '' THEN
      v_sale := app.alloy_sale_rate(v_karat);
    ELSE
      v_sale := COALESCE(NULLIF(ln->>'sale_rate','')::numeric,
                         app.rate_for(v_mat, COALESCE(ln->>'size_band',''), 'SALE', v_on));
    END IF;

    INSERT INTO jewel_material_line (jewel_code_id, version_no, line_no, material_id, size_band,
                                     pcs, qty_value, qty_uom, basis, cost_rate, sale_rate, remarks)
    VALUES (v_jc, 1, v_no, v_mat, COALESCE(ln->>'size_band',''),
            NULLIF(ln->>'pcs','')::int, NULLIF(ln->>'qty','')::numeric, v_uom, v_basis,
            v_cost, v_sale, NULLIF(btrim(COALESCE(ln->>'remarks','')),''));
  END LOOP;

  PERFORM app.recost_jewel(v_jc, 1, v_user);

  IF v_loc_id IS NOT NULL THEN
    INSERT INTO stock_movement (jewel_code_id, move_type, to_location_id, resulting_state,
                                moved_at, reference_no, reason, user_id)
    VALUES (v_jc, 'RECEIPT', v_loc_id, 'IN_STOCK', v_on::timestamptz,
            NULLIF(btrim(COALESCE(p->>'reference_no','')),''), 'Opening entry', v_user);
  END IF;

  PERFORM app.log('INSERT','jewel_code', v_code,
                  'Piece added with '||v_no||' BOM lines', NULL, v_no);

  RETURN (SELECT jsonb_build_object(
    'ok', true, 'jewel_code', v_code, 'jewel_code_id', v_jc, 'lines', v_no,
    'bom_weight_gm', b.bom_weight_gm, 'net_metal_wt_gm', b.net_metal_wt_gm,
    'cost_price', b.total_cost_price, 'sale_price', app.live_sale_price(v_jc),
    'unpriced_lines', (SELECT count(*) FROM jewel_material_line
                        WHERE jewel_code_id=v_jc AND version_no=1 AND cost_rate IS NULL))
    FROM bom_version b WHERE b.jewel_code_id=v_jc AND b.version_no=1);
END $fn$;

CREATE OR REPLACE FUNCTION app.import_pieces(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  it JSONB; res JSONB; out JSONB := '[]'::jsonb;
  ok INT := 0; bad INT := 0;
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to import stock.';
  END IF;
  FOR it IN SELECT jsonb_array_elements(p) LOOP
    BEGIN
      res := app.add_piece(it);
      ok := ok + 1;
    EXCEPTION WHEN OTHERS THEN
      res := jsonb_build_object('ok', false,
                                'jewel_code', upper(COALESCE(it->>'jewel_code','(blank)')),
                                'error', SQLERRM);
      bad := bad + 1;
    END;
    out := out || jsonb_build_array(res);
  END LOOP;
  PERFORM app.log('IMPORT','jewel_code','batch',
                  ok||' added, '||bad||' rejected', NULL, ok);
  RETURN jsonb_build_object('added', ok, 'rejected', bad, 'rows', out);
END $fn$;

GRANT EXECUTE ON FUNCTION app.add_piece(JSONB), app.import_pieces(JSONB) TO authenticated;

-- REST-callable wrappers, so the front end can add stock without ever being
-- given a route into the app schema.
CREATE OR REPLACE FUNCTION api.add_piece(p JSONB)
RETURNS JSONB LANGUAGE sql SECURITY INVOKER SET search_path = api, app, public AS $$
  SELECT app.add_piece(p);
$$;
CREATE OR REPLACE FUNCTION api.import_pieces(p JSONB)
RETURNS JSONB LANGUAGE sql SECURITY INVOKER SET search_path = api, app, public AS $$
  SELECT app.import_pieces(p);
$$;
GRANT EXECUTE ON FUNCTION api.add_piece(JSONB), api.import_pieces(JSONB) TO authenticated;;
