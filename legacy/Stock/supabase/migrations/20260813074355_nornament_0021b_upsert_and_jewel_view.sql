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
  v_has   INT; v_state stock_state; k TEXT; v_cur TEXT;
  v_map   CONSTANT JSONB := jsonb_build_object(
    'karat','metal_purity', 'colour','metal_colour', 'size','size_label',
    'quality','diamond_quality', 'gross_wt','measured_gross_wt_gm',
    'length_mm','length_mm', 'breadth_mm','breadth_mm', 'height_mm','height_mm',
    'huid','huid', 'hallmarked_on','hallmarked_on', 'hallmark_centre','hallmark_centre',
    'remarks','remarks', 'sub_category','sub_category', 'src_system','src_system',
    'src_ref','src_ref', 'src_cost_price','src_cost_price', 'src_sale_price','src_sale_price',
    'src_tag_price','src_tag_price', 'src_net_wt_gm','src_net_wt_gm');
BEGIN
  SELECT jewel_code_id, stock_state INTO v_jc, v_state
    FROM jewel_code WHERE upper(jewel_code) = v_code;
  IF v_jc IS NULL THEN
    RETURN app.add_piece(p) || jsonb_build_object('action','added');
  END IF;
  IF v_state IN ('SOLD','MELTED','LOST') THEN
    RAISE EXCEPTION 'Jewel code % is %. Closed pieces are history and are not re-imported.',
      v_code, v_state;
  END IF;

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
  IF (p ? 'collection') AND COALESCE(p->>'collection','') <> '' THEN
    v_patch := v_patch || jsonb_build_object('collection', p->>'collection');
  END IF;
  IF v_patch <> '{}'::jsonb THEN
    PERFORM app.update_piece(v_patch || jsonb_build_object('jewel_code', v_code));
  END IF;

  IF jsonb_array_length(v_lines) > 0 THEN
    SELECT count(*) INTO v_has FROM jewel_material_line l JOIN jewel_code j USING (jewel_code_id)
     WHERE l.jewel_code_id = v_jc AND l.version_no = j.current_bom_version;
    IF v_has = 0 THEN
      PERFORM app.set_bom(jsonb_build_object('jewel_code', v_code, 'lines', v_lines,
                'is_summary', COALESCE((p->>'bom_is_summary')::boolean, FALSE)));
      v_did := v_did || ('materials (' || jsonb_array_length(v_lines) || ' lines)');
    ELSIF v_over THEN
      PERFORM app.set_bom(jsonb_build_object('jewel_code', v_code, 'lines', v_lines,
                'is_summary', COALESCE((p->>'bom_is_summary')::boolean, FALSE),
                'note','Replaced from spreadsheet upload'));
      v_did := v_did || 'materials replaced, new BOM version';
    END IF;
  END IF;

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

DROP VIEW IF EXISTS api.jewel;
CREATE VIEW api.jewel AS
SELECT
  jc.jewel_code_id, jc.jewel_code, s.style_code, s.name AS design_name,
  c.name AS category, col.name AS collection, jc.sub_category,
  jc.metal_purity AS karat, jc.metal_colour, jc.size_label, jc.diamond_quality,
  jc.measured_gross_wt_gm, b.net_metal_wt_gm, b.bom_weight_gm,
  ROUND(jc.measured_gross_wt_gm - b.bom_weight_gm, 3) AS weight_diff_gm,
  jc.length_mm, jc.breadth_mm, jc.height_mm,
  jc.stock_state, l.code AS location_code, l.name AS location,
  jc.received_on, jc.disposed_on, jc.huid, jc.hallmarked_on, jc.hallmark_centre,
  b.version_no AS bom_version, b.reason AS bom_reason,
  CASE WHEN app.has_cap('sale') THEN app.live_sale_price(jc.jewel_code_id) END AS sale_price,
  CASE WHEN app.has_cap('sale') THEN app.alloy_sale_rate(jc.metal_purity) END AS gold_rate_used,
  CASE WHEN app.has_cap('sale')
       THEN (SELECT value FROM app.system_setting WHERE key='pure_gold_rate_as_on') END AS price_as_on,
  CASE WHEN app.has_cap('cost') THEN b.total_cost_price END AS cost_price,
  CASE WHEN app.has_cap('margin')
       THEN app.live_sale_price(jc.jewel_code_id) - b.total_cost_price END AS margin,
  CASE WHEN app.has_cap('vendor') THEN v.code END AS vendor_code,
  CASE WHEN app.has_cap('vendor') THEN v.name END AS vendor_name,
  CASE WHEN app.has_cap('vendor') THEN v.avg_tat_days END AS vendor_avg_tat_days,
  jc.on_website, jc.website_url, jc.remarks, jc.updated_at,
  app.piece_gaps(jc.jewel_code_id) AS missing,
  (SELECT count(*) FROM app.jewel_material_line ml
    WHERE ml.jewel_code_id = jc.jewel_code_id
      AND ml.version_no = jc.current_bom_version) AS bom_lines,
  jc.bom_is_summary, jc.src_system, jc.src_ref, jc.src_net_wt_gm,
  CASE WHEN app.has_cap('cost') THEN jc.src_cost_price END AS src_cost_price,
  CASE WHEN app.has_cap('sale') THEN jc.src_sale_price END AS src_sale_price,
  CASE WHEN app.has_cap('sale') THEN jc.src_tag_price  END AS src_tag_price
FROM app.jewel_code jc
JOIN app.style s        ON s.style_id = jc.style_id
JOIN app.category c     ON c.category_id = s.category_id
LEFT JOIN app.collection col ON col.collection_id = s.collection_id
LEFT JOIN app.location l     ON l.location_id = jc.location_id
LEFT JOIN app.vendor v       ON v.vendor_id = jc.vendor_id
LEFT JOIN app.bom_version b  ON b.jewel_code_id = jc.jewel_code_id AND b.is_current
WHERE jc.location_id IS NULL OR jc.location_id IN (SELECT app.visible_locations());
GRANT SELECT ON api.jewel TO authenticated;;
