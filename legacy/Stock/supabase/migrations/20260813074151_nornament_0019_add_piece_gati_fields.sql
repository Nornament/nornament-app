-- add_piece / upsert_piece learn the rest of the Gati columns: sub category,
-- collection, the source system's own figures, and the summary flag.
SET search_path TO app, public;

-- categories: "Earring" and "Earrings" are the same thing, and a collection
-- that does not exist yet is a new collection, not an error.
CREATE OR REPLACE FUNCTION app.resolve_category(p TEXT)
RETURNS INT LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT category_id FROM category
   WHERE upper(code) = upper(btrim(p)) OR upper(name) = upper(btrim(p))
      OR upper(regexp_replace(name,'s$','','i')) = upper(regexp_replace(btrim(p),'s$','','i'))
   ORDER BY sort_order LIMIT 1;
$$;
CREATE OR REPLACE FUNCTION app.resolve_collection(p TEXT)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v INT;
BEGIN
  IF COALESCE(btrim(p),'') = '' THEN RETURN NULL; END IF;
  SELECT collection_id INTO v FROM collection WHERE upper(name) = upper(btrim(p));
  IF v IS NULL THEN
    INSERT INTO collection (name) VALUES (btrim(p)) RETURNING collection_id INTO v;
  END IF;
  RETURN v;
END $fn$;
GRANT EXECUTE ON FUNCTION app.resolve_category(TEXT), app.resolve_collection(TEXT) TO authenticated;

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
      INSERT INTO vendor (code, name)
      VALUES (upper(left(regexp_replace(p->>'vendor','[^A-Za-z0-9]','','g'),12)), btrim(p->>'vendor'))
      RETURNING vendor_id INTO v_ven_id;
    END IF;
  END IF;

  SELECT style_id INTO v_style_id FROM style WHERE upper(style_code)=v_style;
  IF v_style_id IS NULL THEN
    v_cat_id := app.resolve_category(COALESCE(p->>'category',''));
    IF v_cat_id IS NULL THEN
      RAISE EXCEPTION 'Design % is new, so it needs a category. "%" is not one of: %',
        v_style, COALESCE(p->>'category','(blank)'),
        (SELECT string_agg(name,', ' ORDER BY sort_order) FROM category);
    END IF;
    INSERT INTO style (style_code, name, category_id, collection_id, state, nos_min_qty, created_by)
    VALUES (v_style, NULLIF(btrim(COALESCE(p->>'design_name','')),''), v_cat_id,
            app.resolve_collection(p->>'collection'),
            'IN_STOCK_DESIGN', COALESCE(NULLIF(p->>'nos_min_qty','')::int,0), v_user)
    RETURNING style_id INTO v_style_id;
  ELSIF COALESCE(p->>'collection','') <> '' THEN
    UPDATE style SET collection_id = app.resolve_collection(p->>'collection')
     WHERE style_id = v_style_id AND collection_id IS NULL;
  END IF;

  INSERT INTO jewel_code (jewel_code, style_id, metal_purity, metal_colour, size_label,
                          diamond_quality, measured_gross_wt_gm, length_mm, breadth_mm, height_mm,
                          huid, hallmarked_on, hallmark_centre, vendor_id, remarks,
                          sub_category, src_system, src_ref, src_cost_price, src_sale_price,
                          src_tag_price, src_net_wt_gm, bom_is_summary,
                          stock_state, current_bom_version, created_by)
  VALUES (v_code, v_style_id, NULLIF(v_karat,''), NULLIF(btrim(COALESCE(p->>'colour','')),''),
          NULLIF(btrim(COALESCE(p->>'size','')),''), NULLIF(btrim(COALESCE(p->>'quality','')),''),
          NULLIF(p->>'gross_wt','')::numeric, NULLIF(p->>'length_mm','')::numeric,
          NULLIF(p->>'breadth_mm','')::numeric, NULLIF(p->>'height_mm','')::numeric,
          NULLIF(btrim(COALESCE(p->>'huid','')),''), NULLIF(p->>'hallmarked_on','')::date,
          NULLIF(btrim(COALESCE(p->>'hallmark_centre','')),''), v_ven_id,
          NULLIF(btrim(COALESCE(p->>'remarks','')),''),
          NULLIF(btrim(COALESCE(p->>'sub_category','')),''),
          NULLIF(btrim(COALESCE(p->>'src_system','')),''),
          NULLIF(btrim(COALESCE(p->>'src_ref','')),''),
          NULLIF(p->>'src_cost_price','')::numeric, NULLIF(p->>'src_sale_price','')::numeric,
          NULLIF(p->>'src_tag_price','')::numeric, NULLIF(p->>'src_net_wt_gm','')::numeric,
          COALESCE((p->>'bom_is_summary')::boolean, FALSE),
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
END $fn$;;
