-- Dropdowns for the entry form, without giving the front end any route
-- into the app schema. Reference data only - nothing priced, nothing costed.
CREATE OR REPLACE VIEW api.reference AS
SELECT 'category' AS kind, code, name AS label, NULL::text AS extra, sort_order AS ord
  FROM app.category
UNION ALL
SELECT 'location', code, name, kind, location_id FROM app.location WHERE is_active
UNION ALL
SELECT 'karat', karat, karat, (sale_factor*100)::text || '%', 0 FROM app.metal_purity
UNION ALL
SELECT 'colour', c, c, NULL, 0 FROM (VALUES ('Yellow'),('White'),('Rose'),('Two-tone')) v(c)
UNION ALL
SELECT 'material', item_code, item_name, mat_class::text || '|' || default_uom::text, material_id
  FROM app.material WHERE is_active
UNION ALL
SELECT DISTINCT 'size_band', l.size_band, l.size_band, m.item_code, 0
  FROM app.rate_card_line l JOIN app.material m USING (material_id)
 WHERE l.size_band <> ''
UNION ALL
SELECT 'basis', b, b, NULL, 0
  FROM (VALUES ('BY_QTY'),('BY_NET_METAL_WT'),('BY_PIECE'),('FLAT')) v(b)
UNION ALL
SELECT 'uom', u, u, NULL, 0 FROM (VALUES ('CT'),('GM'),('RATTI'),('PCS')) v(u)
UNION ALL
SELECT 'style', style_code, COALESCE(name, style_code),
       (SELECT c.name FROM app.category c WHERE c.category_id = s.category_id), style_id
  FROM app.style s WHERE is_active;

GRANT SELECT ON api.reference TO authenticated;

-- api.jewel gains the gap list, so the form can show what is still owed
-- on each piece instead of the person having to remember.
CREATE OR REPLACE VIEW api.jewel AS
SELECT
  jc.jewel_code_id, jc.jewel_code, s.style_code, s.name AS design_name,
  c.name AS category, col.name AS collection,
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
      AND ml.version_no = jc.current_bom_version) AS bom_lines
FROM app.jewel_code jc
JOIN app.style s        ON s.style_id = jc.style_id
JOIN app.category c     ON c.category_id = s.category_id
LEFT JOIN app.collection col ON col.collection_id = s.collection_id
LEFT JOIN app.location l     ON l.location_id = jc.location_id
LEFT JOIN app.vendor v       ON v.vendor_id = jc.vendor_id
LEFT JOIN app.bom_version b  ON b.jewel_code_id = jc.jewel_code_id AND b.is_current
WHERE jc.location_id IS NULL OR jc.location_id IN (SELECT app.visible_locations());

GRANT SELECT ON api.jewel TO authenticated;;
