
-- The BOM screen marks a line that disagrees with the rate chart. The flag
-- has to reach it, along with the category the line groups under.
DROP VIEW IF EXISTS api.bom_line;

CREATE VIEW api.bom_line
WITH (security_invoker = false) AS
SELECT jc.jewel_code, l.version_no, bv.reason AS version_reason, bv.is_current,
       l.line_no, m.item_code AS material_code, m.item_name AS material_name,
       m.mat_class AS material_class,
       m.category AS material_category, mc.name AS category_name, mc.sort_order AS category_order,
       l.size_band, l.pcs, l.qty_value, l.qty_uom, l.basis, l.off_chart,
       CASE WHEN app.has_cap('cost') THEN l.cost_rate END AS cost_rate,
       CASE WHEN app.has_cap('cost') THEN l.cost_amount END AS cost_amount,
       -- what this line would cost at today's metal rate
       CASE WHEN app.has_cap('cost') THEN
         CASE WHEN m.mat_class = 'METAL'
              THEN round(app.alloy_cost_rate(jc.metal_purity) * COALESCE(l.qty_value,0), 0)
              ELSE l.cost_amount END END AS cost_amount_today,
       CASE WHEN app.has_cap('sale') THEN
         CASE WHEN m.mat_class = 'METAL' THEN app.alloy_sale_rate(jc.metal_purity)
              ELSE l.sale_rate END END AS sale_rate,
       CASE WHEN app.has_cap('sale') THEN
         CASE WHEN m.mat_class = 'METAL'
              THEN round(app.alloy_sale_rate(jc.metal_purity) * COALESCE(l.qty_value,0), 0)
              ELSE l.sale_amount END END AS sale_amount
  FROM app.jewel_material_line l
  JOIN app.jewel_code jc ON jc.jewel_code_id = l.jewel_code_id
  JOIN app.material m ON m.material_id = l.material_id
  JOIN app.material_category mc ON mc.code = m.category
  JOIN app.bom_version bv ON bv.jewel_code_id = l.jewel_code_id AND bv.version_no = l.version_no
 WHERE app.has_cap('materials')
   AND (jc.location_id IS NULL OR jc.location_id IN (SELECT app.visible_locations()));

GRANT SELECT ON api.bom_line TO anon, authenticated;
;
