-- ============================================================
-- 0018  What the Gati export actually needs.
--
-- 1. Item names are not a fixed master. The file carries 12 diamond
--    codes and 20+ stone codes, and there will be more next month.
--    So a material is registered the first time it is seen instead
--    of the row being refused. The master still exists - it just
--    grows by itself, which keeps aggregation possible later.
-- 2. Only gold is dynamic. Diamonds and stones carry their rate on
--    the line, exactly as the sheet does. Nothing looks them up.
-- 3. Gati's own Cost Price / Sale Price / Tag Price are kept beside
--    the piece as recorded figures, so a BOM built later can be
--    checked against what the old system said.
-- ============================================================
SET search_path TO app, public;

INSERT INTO metal_purity (karat, sale_factor, true_fineness)
SELECT '925', 0.925, 0.925
WHERE NOT EXISTS (SELECT 1 FROM metal_purity WHERE karat='925');

ALTER TABLE jewel_code
  ADD COLUMN IF NOT EXISTS sub_category   TEXT,
  ADD COLUMN IF NOT EXISTS src_system     TEXT,
  ADD COLUMN IF NOT EXISTS src_ref        TEXT,
  ADD COLUMN IF NOT EXISTS src_cost_price NUMERIC,
  ADD COLUMN IF NOT EXISTS src_sale_price NUMERIC,
  ADD COLUMN IF NOT EXISTS src_tag_price  NUMERIC,
  ADD COLUMN IF NOT EXISTS src_net_wt_gm  NUMERIC,
  ADD COLUMN IF NOT EXISTS bom_is_summary BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN jewel_code.bom_is_summary IS
 'TRUE when the material lines came from a summary export that shows only one '
 'line per material type. The cost derived from those lines understates the piece. '
 'Cleared when a real bill of materials is loaded.';

-- Find a material by code, or register it. Free text in, a real row out.
CREATE OR REPLACE FUNCTION app.resolve_material(p_code TEXT, p_name TEXT DEFAULT NULL,
                                                p_class TEXT DEFAULT NULL,
                                                p_uom TEXT DEFAULT NULL)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  v_code TEXT := upper(btrim(COALESCE(NULLIF(btrim(p_code),''), p_name)));
  v_id INT; v_class material_class; v_uom uom;
BEGIN
  IF COALESCE(v_code,'') = '' THEN RETURN NULL; END IF;
  SELECT material_id INTO v_id FROM material WHERE upper(item_code) = v_code;
  IF v_id IS NOT NULL THEN RETURN v_id; END IF;
  SELECT material_id INTO v_id FROM material WHERE upper(item_name) = upper(btrim(p_name));
  IF v_id IS NOT NULL THEN RETURN v_id; END IF;

  -- work out what kind of thing it is, from the caller's hint or the code itself
  v_class := CASE
    WHEN p_class IS NOT NULL AND p_class <> '' THEN p_class::material_class
    WHEN v_code ~ '^(G|S)[0-9]' OR v_code ~ '^GC?[0-9]' THEN 'METAL'
    WHEN v_code LIKE 'D%'   THEN 'DIAMOND'
    WHEN v_code LIKE 'FPL%' OR v_code LIKE 'PL%' THEN 'POLKI'
    WHEN v_code LIKE 'P%'   THEN 'PEARL'
    WHEN v_code LIKE 'S%'   THEN 'COLOUR_STONE'
    ELSE 'OTHER' END;
  v_uom := CASE
    WHEN p_uom IS NOT NULL AND p_uom <> '' THEN upper(p_uom)::uom
    WHEN v_class = 'METAL' THEN 'GM'
    WHEN v_class IN ('DIAMOND','POLKI','COLOUR_STONE','PEARL') THEN 'CT'
    ELSE 'PCS' END;

  INSERT INTO material (item_code, item_name, mat_class, default_uom, is_active)
  VALUES (v_code, COALESCE(NULLIF(btrim(p_name),''), v_code), v_class, v_uom, TRUE)
  RETURNING material_id INTO v_id;
  PERFORM app.log('INSERT','material', v_code,
                  'Registered automatically as '||v_class||' / '||v_uom||' on first use');
  RETURN v_id;
END $fn$;

-- Line writer, now free-text aware and taking rates straight off the line.
CREATE OR REPLACE FUNCTION app.write_bom_lines(p_jc INT, p_ver INT, p_lines JSONB,
                                               p_karat TEXT, p_on DATE)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, public AS $fn$
DECLARE
  ln JSONB; v_no INT := 0; v_mat INT; v_class material_class;
  v_uom uom; v_basis charge_basis; v_cost NUMERIC; v_sale NUMERIC;
BEGIN
  FOR ln IN SELECT jsonb_array_elements(p_lines) LOOP
    v_no := v_no + 1;
    v_mat := app.resolve_material(ln->>'material', ln->>'material_name',
                                  NULLIF(ln->>'material_class',''), NULLIF(ln->>'uom',''));
    IF v_mat IS NULL THEN
      RAISE EXCEPTION 'Line %: no material code or name given.', v_no;
    END IF;
    SELECT mat_class, default_uom INTO v_class, v_uom FROM material WHERE material_id = v_mat;
    IF COALESCE(ln->>'uom','') <> '' THEN v_uom := (upper(btrim(ln->>'uom')))::uom; END IF;
    IF v_class = 'METAL' AND v_uom <> 'GM' THEN v_uom := 'GM'; END IF;
    v_basis := COALESCE(NULLIF(upper(btrim(COALESCE(ln->>'basis',''))),''),'BY_QTY')::charge_basis;
    IF v_class='LABOUR' AND NULLIF(ln->>'qty','') IS NULL AND v_basis='BY_QTY' THEN
      v_basis := 'BY_NET_METAL_WT';
    END IF;

    -- the sheet wins. only fall back to the rate card when the sheet is silent.
    v_cost := COALESCE(NULLIF(ln->>'cost_rate','')::numeric,
                       app.rate_for(v_mat, COALESCE(ln->>'size_band',''), 'COST', p_on));
    IF v_class = 'METAL' AND COALESCE(p_karat,'') <> '' THEN
      v_sale := app.alloy_sale_rate(p_karat);          -- gold is the only dynamic one
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

GRANT EXECUTE ON FUNCTION app.resolve_material(TEXT,TEXT,TEXT,TEXT) TO authenticated;;
