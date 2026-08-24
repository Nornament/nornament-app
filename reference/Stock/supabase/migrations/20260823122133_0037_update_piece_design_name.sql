
-- update_piece could not set the design name, and treated an empty collection
-- as "leave it alone" so a collection could never be cleared. The edit form
-- offers both, so both have to work.
CREATE OR REPLACE FUNCTION app.update_piece(p jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE v_code TEXT := upper(btrim(p->>'jewel_code'));
        v_jc INT; v_ven INT; v_style INT; v_changed TEXT := '';
BEGIN
  IF NOT app.is_privileged() THEN
    RAISE EXCEPTION 'You do not have permission to change a piece.';
  END IF;
  SELECT jewel_code_id, style_id INTO v_jc, v_style
    FROM jewel_code WHERE upper(jewel_code) = v_code;
  IF v_jc IS NULL THEN RAISE EXCEPTION 'Jewel code % not found.', v_code; END IF;
  IF (SELECT stock_state FROM jewel_code WHERE jewel_code_id=v_jc)
     IN ('SOLD','MELTED','LOST') THEN
    RAISE EXCEPTION 'Jewel code % is closed. Its record is history now and cannot be edited.', v_code;
  END IF;
  IF p ? 'karat' AND COALESCE(p->>'karat','') <> ''
     AND NOT EXISTS (SELECT 1 FROM metal_purity WHERE karat = upper(btrim(p->>'karat'))) THEN
    RAISE EXCEPTION 'Karat "%" is not set up.', p->>'karat';
  END IF;
  IF p ? 'vendor' AND COALESCE(p->>'vendor','') <> '' THEN
    SELECT vendor_id INTO v_ven FROM vendor
     WHERE upper(code)=upper(btrim(p->>'vendor')) OR upper(name)=upper(btrim(p->>'vendor'));
    IF v_ven IS NULL THEN
      INSERT INTO vendor (code,name)
      VALUES (upper(left(regexp_replace(p->>'vendor','[^A-Za-z0-9]','','g'),12)),
              btrim(p->>'vendor'))
      RETURNING vendor_id INTO v_ven;
    END IF;
  END IF;

  UPDATE jewel_code SET
    metal_purity   = CASE WHEN p ? 'karat' THEN NULLIF(upper(btrim(p->>'karat')),'') ELSE metal_purity END,
    metal_colour   = CASE WHEN p ? 'colour' THEN NULLIF(btrim(p->>'colour'),'') ELSE metal_colour END,
    size_label     = CASE WHEN p ? 'size' THEN NULLIF(btrim(p->>'size'),'') ELSE size_label END,
    diamond_quality= CASE WHEN p ? 'quality' THEN NULLIF(btrim(p->>'quality'),'') ELSE diamond_quality END,
    sub_category   = CASE WHEN p ? 'sub_category' THEN NULLIF(btrim(p->>'sub_category'),'') ELSE sub_category END,
    measured_gross_wt_gm = CASE WHEN p ? 'gross_wt' THEN NULLIF(p->>'gross_wt','')::numeric ELSE measured_gross_wt_gm END,
    length_mm      = CASE WHEN p ? 'length_mm' THEN NULLIF(p->>'length_mm','')::numeric ELSE length_mm END,
    breadth_mm     = CASE WHEN p ? 'breadth_mm' THEN NULLIF(p->>'breadth_mm','')::numeric ELSE breadth_mm END,
    height_mm      = CASE WHEN p ? 'height_mm' THEN NULLIF(p->>'height_mm','')::numeric ELSE height_mm END,
    huid           = CASE WHEN p ? 'huid' THEN NULLIF(btrim(p->>'huid'),'') ELSE huid END,
    hallmarked_on  = CASE WHEN p ? 'hallmarked_on' THEN NULLIF(p->>'hallmarked_on','')::date ELSE hallmarked_on END,
    hallmark_centre= CASE WHEN p ? 'hallmark_centre' THEN NULLIF(btrim(p->>'hallmark_centre'),'') ELSE hallmark_centre END,
    remarks        = CASE WHEN p ? 'remarks' THEN NULLIF(btrim(p->>'remarks'),'') ELSE remarks END,
    vendor_id      = CASE WHEN p ? 'vendor'
                          THEN CASE WHEN COALESCE(p->>'vendor','')='' THEN NULL ELSE v_ven END
                          ELSE vendor_id END,
    on_website     = CASE WHEN p ? 'on_website' THEN (p->>'on_website')::boolean ELSE on_website END,
    website_url    = CASE WHEN p ? 'website_url' THEN NULLIF(btrim(p->>'website_url'),'') ELSE website_url END,
    src_system     = CASE WHEN p ? 'src_system' THEN NULLIF(btrim(p->>'src_system'),'') ELSE src_system END,
    src_ref        = CASE WHEN p ? 'src_ref' THEN NULLIF(btrim(p->>'src_ref'),'') ELSE src_ref END,
    src_cost_price = CASE WHEN p ? 'src_cost_price' THEN NULLIF(p->>'src_cost_price','')::numeric ELSE src_cost_price END,
    src_sale_price = CASE WHEN p ? 'src_sale_price' THEN NULLIF(p->>'src_sale_price','')::numeric ELSE src_sale_price END,
    src_tag_price  = CASE WHEN p ? 'src_tag_price' THEN NULLIF(p->>'src_tag_price','')::numeric ELSE src_tag_price END,
    src_net_wt_gm  = CASE WHEN p ? 'src_net_wt_gm' THEN NULLIF(p->>'src_net_wt_gm','')::numeric ELSE src_net_wt_gm END,
    updated_at     = now()
  WHERE jewel_code_id = v_jc;

  -- the design name lives on the style, and is shared by every piece of it
  IF p ? 'design_name' THEN
    UPDATE style SET name = NULLIF(btrim(p->>'design_name'),'') WHERE style_id = v_style;
  END IF;

  -- an emptied collection now clears, rather than being read as "no change"
  IF p ? 'collection' THEN
    UPDATE style
       SET collection_id = CASE WHEN COALESCE(p->>'collection','') = '' THEN NULL
                                ELSE app.resolve_collection(p->>'collection') END
     WHERE style_id = v_style;
  END IF;

  IF p ? 'karat' THEN
    UPDATE jewel_material_line l
       SET sale_rate = app.alloy_sale_rate(
             (SELECT metal_purity FROM jewel_code WHERE jewel_code_id=v_jc))
      FROM material m
     WHERE m.material_id = l.material_id AND m.mat_class = 'METAL'
       AND l.jewel_code_id = v_jc
       AND l.version_no = (SELECT current_bom_version FROM jewel_code WHERE jewel_code_id=v_jc);
  END IF;

  PERFORM app.recost_jewel(v_jc, NULL, app.current_user_id());
  SELECT string_agg(k, ', ' ORDER BY k) INTO v_changed
    FROM jsonb_object_keys(p) k WHERE k <> 'jewel_code';
  PERFORM app.log('UPDATE','jewel_code', v_code, 'Edited: '||COALESCE(v_changed,'nothing'));
  RETURN app.piece_state(v_jc);
END $fn$;
;
