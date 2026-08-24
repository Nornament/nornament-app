
-- api.jewel gains current_cost beside cost_price, plus the margin measured
-- against it — the number pricing decisions should actually use.
DROP VIEW IF EXISTS api.jewel;

CREATE VIEW api.jewel
WITH (security_invoker = false) AS
SELECT jc.jewel_code_id, jc.jewel_code, s.style_code, s.name AS design_name,
    c.name AS category, col.name AS collection, jc.sub_category,
    jc.metal_purity AS karat, jc.metal_colour, jc.size_label, jc.diamond_quality,
    jc.measured_gross_wt_gm, b.net_metal_wt_gm, b.bom_weight_gm,
    round(jc.measured_gross_wt_gm - b.bom_weight_gm, 3) AS weight_diff_gm,
    jc.length_mm, jc.breadth_mm, jc.height_mm,
    jc.stock_state, l.code AS location_code, l.name AS location,
    jc.received_on, jc.disposed_on, jc.huid, jc.hallmarked_on, jc.hallmark_centre,
    b.version_no AS bom_version, b.reason AS bom_reason,
    CASE WHEN app.has_cap('sale') THEN app.live_sale_price(jc.jewel_code_id) END AS sale_price,
    CASE WHEN app.has_cap('sale') THEN app.alloy_sale_rate(jc.metal_purity) END AS gold_rate_used,
    CASE WHEN app.has_cap('sale')
         THEN to_char((SELECT max(rate_as_on) FROM app.metal), 'YYYY-MM-DD HH24:MI') END AS price_as_on,
    CASE WHEN app.has_cap('cost') THEN b.total_cost_price END AS cost_price,
    -- what the same piece would cost to make today
    CASE WHEN app.has_cap('cost') THEN app.current_cost(jc.jewel_code_id) END AS current_cost,
    CASE WHEN app.has_cap('cost') THEN app.alloy_cost_rate(jc.metal_purity) END AS metal_cost_rate,
    CASE WHEN app.has_cap('margin')
         THEN app.live_sale_price(jc.jewel_code_id) - b.total_cost_price END AS margin,
    CASE WHEN app.has_cap('margin')
         THEN app.live_sale_price(jc.jewel_code_id) - app.current_cost(jc.jewel_code_id) END AS current_margin,
    CASE WHEN app.has_cap('vendor') THEN v.code END AS vendor_code,
    CASE WHEN app.has_cap('vendor') THEN v.name END AS vendor_name,
    CASE WHEN app.has_cap('vendor') THEN v.avg_tat_days END AS vendor_avg_tat_days,
    jc.on_website, jc.website_url, jc.remarks, jc.updated_at,
    app.piece_gaps(jc.jewel_code_id) AS missing,
    (SELECT count(*) FROM app.jewel_material_line ml
      WHERE ml.jewel_code_id = jc.jewel_code_id AND ml.version_no = jc.current_bom_version) AS bom_lines,
    jc.bom_is_summary, jc.src_system, jc.src_ref, jc.src_net_wt_gm,
    CASE WHEN app.has_cap('cost') THEN jc.src_cost_price END AS src_cost_price,
    CASE WHEN app.has_cap('sale') THEN jc.src_sale_price END AS src_sale_price,
    CASE WHEN app.has_cap('sale') THEN jc.src_tag_price END AS src_tag_price
  FROM app.jewel_code jc
  JOIN app.style s ON s.style_id = jc.style_id
  JOIN app.category c ON c.category_id = s.category_id
  LEFT JOIN app.collection col ON col.collection_id = s.collection_id
  LEFT JOIN app.location l ON l.location_id = jc.location_id
  LEFT JOIN app.vendor v ON v.vendor_id = jc.vendor_id
  LEFT JOIN app.bom_version b ON b.jewel_code_id = jc.jewel_code_id AND b.is_current
 WHERE jc.location_id IS NULL OR jc.location_id IN (SELECT app.visible_locations());

GRANT SELECT ON api.jewel TO anon, authenticated;
;
