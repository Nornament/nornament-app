SET search_path TO app, public;

-- the gap list now knows the difference between "no materials" and
-- "materials that are only a summary and cannot be trusted for cost"
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
      SELECT 'Full BOM (only a summary so far)', 4
        FROM jewel_code WHERE jewel_code_id=p_jc AND bom_is_summary
      UNION ALL
      SELECT 'Rates on '||count(*)||' material line(s)', 5
        FROM jewel_material_line l JOIN jewel_code j USING (jewel_code_id)
       WHERE l.jewel_code_id=p_jc AND l.version_no=j.current_bom_version AND l.cost_rate IS NULL
       HAVING count(*) > 0
      UNION ALL
      SELECT 'Not received into any location', 6
        WHERE (SELECT stock_state FROM jewel_code WHERE jewel_code_id=p_jc) = 'NOT_RECEIVED'
      UNION ALL
      SELECT 'Photograph', 7 WHERE NOT EXISTS (
        SELECT 1 FROM media_asset WHERE jewel_code_id=p_jc AND kind='PHOTO')
    ) x ORDER BY o);
$$;

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
  IF (SELECT stock_state FROM jewel_code WHERE jewel_code_id=v_jc) IN ('SOLD','MELTED','LOST') THEN
    RAISE EXCEPTION 'Jewel code % is closed. Its record is history now and cannot be edited.', v_code;
  END IF;
  IF p ? 'karat' AND COALESCE(p->>'karat','') <> ''
     AND NOT EXISTS (SELECT 1 FROM metal_purity WHERE karat=upper(btrim(p->>'karat'))) THEN
    RAISE EXCEPTION 'Karat "%" is not set up.', p->>'karat';
  END IF;
  IF p ? 'vendor' AND COALESCE(p->>'vendor','') <> '' THEN
    SELECT vendor_id INTO v_ven FROM vendor
     WHERE upper(code)=upper(btrim(p->>'vendor')) OR upper(name)=upper(btrim(p->>'vendor'));
    IF v_ven IS NULL THEN
      INSERT INTO vendor (code,name)
      VALUES (upper(left(regexp_replace(p->>'vendor','[^A-Za-z0-9]','','g'),12)), btrim(p->>'vendor'))
      RETURNING vendor_id INTO v_ven;
    END IF;
  END IF;

  UPDATE jewel_code SET
    metal_purity   = CASE WHEN p ? 'karat'   THEN NULLIF(upper(btrim(p->>'karat')),'') ELSE metal_purity END,
    metal_colour   = CASE WHEN p ? 'colour'  THEN NULLIF(btrim(p->>'colour'),'')  ELSE metal_colour END,
    size_label     = CASE WHEN p ? 'size'    THEN NULLIF(btrim(p->>'size'),'')    ELSE size_label END,
    diamond_quality= CASE WHEN p ? 'quality' THEN NULLIF(btrim(p->>'quality'),'') ELSE diamond_quality END,
    sub_category   = CASE WHEN p ? 'sub_category' THEN NULLIF(btrim(p->>'sub_category'),'') ELSE sub_category END,
    measured_gross_wt_gm = CASE WHEN p ? 'gross_wt'  THEN NULLIF(p->>'gross_wt','')::numeric  ELSE measured_gross_wt_gm END,
    length_mm      = CASE WHEN p ? 'length_mm'  THEN NULLIF(p->>'length_mm','')::numeric  ELSE length_mm END,
    breadth_mm     = CASE WHEN p ? 'breadth_mm' THEN NULLIF(p->>'breadth_mm','')::numeric ELSE breadth_mm END,
    height_mm      = CASE WHEN p ? 'height_mm'  THEN NULLIF(p->>'height_mm','')::numeric  ELSE height_mm END,
    huid           = CASE WHEN p ? 'huid'       THEN NULLIF(btrim(p->>'huid'),'')  ELSE huid END,
    hallmarked_on  = CASE WHEN p ? 'hallmarked_on'   THEN NULLIF(p->>'hallmarked_on','')::date ELSE hallmarked_on END,
    hallmark_centre= CASE WHEN p ? 'hallmark_centre' THEN NULLIF(btrim(p->>'hallmark_centre'),'') ELSE hallmark_centre END,
    remarks        = CASE WHEN p ? 'remarks'    THEN NULLIF(btrim(p->>'remarks'),'') ELSE remarks END,
    vendor_id      = CASE WHEN p ? 'vendor'     THEN v_ven ELSE vendor_id END,
    on_website     = CASE WHEN p ? 'on_website' THEN (p->>'on_website')::boolean ELSE on_website END,
    website_url    = CASE WHEN p ? 'website_url'THEN NULLIF(btrim(p->>'website_url'),'') ELSE website_url END,
    src_system     = CASE WHEN p ? 'src_system' THEN NULLIF(btrim(p->>'src_system'),'') ELSE src_system END,
    src_ref        = CASE WHEN p ? 'src_ref'    THEN NULLIF(btrim(p->>'src_ref'),'')    ELSE src_ref END,
    src_cost_price = CASE WHEN p ? 'src_cost_price' THEN NULLIF(p->>'src_cost_price','')::numeric ELSE src_cost_price END,
    src_sale_price = CASE WHEN p ? 'src_sale_price' THEN NULLIF(p->>'src_sale_price','')::numeric ELSE src_sale_price END,
    src_tag_price  = CASE WHEN p ? 'src_tag_price'  THEN NULLIF(p->>'src_tag_price','')::numeric  ELSE src_tag_price END,
    src_net_wt_gm  = CASE WHEN p ? 'src_net_wt_gm'  THEN NULLIF(p->>'src_net_wt_gm','')::numeric  ELSE src_net_wt_gm END,
    updated_at     = now()
  WHERE jewel_code_id = v_jc;

  IF p ? 'collection' AND COALESCE(p->>'collection','') <> '' THEN
    UPDATE style SET collection_id = app.resolve_collection(p->>'collection')
     WHERE style_id = (SELECT style_id FROM jewel_code WHERE jewel_code_id=v_jc);
  END IF;
  IF p ? 'karat' THEN
    UPDATE jewel_material_line l SET sale_rate = app.alloy_sale_rate(
             (SELECT metal_purity FROM jewel_code WHERE jewel_code_id=v_jc))
      FROM material m
     WHERE m.material_id=l.material_id AND m.mat_class='METAL' AND l.jewel_code_id=v_jc
       AND l.version_no=(SELECT current_bom_version FROM jewel_code WHERE jewel_code_id=v_jc);
  END IF;
  PERFORM app.recost_jewel(v_jc, NULL, app.current_user_id());

  SELECT string_agg(k,', ' ORDER BY k) INTO v_changed
    FROM jsonb_object_keys(p) k WHERE k <> 'jewel_code';
  PERFORM app.log('UPDATE','jewel_code',v_code,'Filled in: '||COALESCE(v_changed,'nothing'));
  RETURN app.piece_state(v_jc);
END $fn$;

-- a hand-built BOM clears the summary flag: it is now a real breakup
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
    v_new := v_cur;
  ELSE
    SELECT max(version_no)+1 INTO v_new FROM bom_version WHERE jewel_code_id=v_jc;
    UPDATE bom_version SET is_current=FALSE WHERE jewel_code_id=v_jc AND is_current;
    INSERT INTO bom_version (jewel_code_id, version_no, reason, note, is_current, created_by)
    VALUES (v_jc, v_new, 'CORRECTION', NULLIF(btrim(COALESCE(p->>'note','')),''), TRUE, v_user);
    UPDATE jewel_code SET current_bom_version=v_new, updated_at=now() WHERE jewel_code_id=v_jc;
  END IF;

  v_n := app.write_bom_lines(v_jc, v_new, v_lines, v_karat, CURRENT_DATE);
  UPDATE jewel_code
     SET bom_is_summary = COALESCE((p->>'is_summary')::boolean, FALSE), updated_at = now()
   WHERE jewel_code_id = v_jc;
  PERFORM app.recost_jewel(v_jc, v_new, v_user);
  PERFORM app.log('UPDATE','bom_version', v_code,
                  CASE WHEN v_has=0 THEN 'BOM filled in ('||v_n||' lines)'
                       ELSE 'BOM corrected, version '||v_new||' ('||v_n||' lines)' END,
                  NULL, v_n);
  RETURN app.piece_state(v_jc);
END $fn$;

CREATE OR REPLACE FUNCTION app.piece_state(p_jc INT)
RETURNS JSONB LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  SELECT jsonb_build_object(
    'ok', true, 'jewel_code', j.jewel_code, 'jewel_code_id', j.jewel_code_id,
    'stock_state', j.stock_state::text, 'bom_version', j.current_bom_version,
    'lines', (SELECT count(*) FROM jewel_material_line
               WHERE jewel_code_id=p_jc AND version_no=j.current_bom_version),
    'bom_weight_gm', b.bom_weight_gm, 'net_metal_wt_gm', b.net_metal_wt_gm,
    'cost_price', b.total_cost_price, 'sale_price', app.live_sale_price(p_jc),
    'src_cost_price', j.src_cost_price, 'src_sale_price', j.src_sale_price,
    'bom_is_summary', j.bom_is_summary,
    'missing', to_jsonb(app.piece_gaps(p_jc)))
  FROM jewel_code j
  LEFT JOIN bom_version b ON b.jewel_code_id=j.jewel_code_id AND b.is_current
  WHERE j.jewel_code_id = p_jc;
$$;;
