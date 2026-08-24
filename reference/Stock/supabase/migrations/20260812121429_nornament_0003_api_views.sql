CREATE SCHEMA IF NOT EXISTS api;
GRANT USAGE ON SCHEMA api TO authenticated;
SET search_path TO api, app, public;
CREATE OR REPLACE VIEW api.jewel AS
SELECT
  jc.jewel_code_id,
  jc.jewel_code,
  s.style_code,
  s.name              AS design_name,
  c.name              AS category,
  col.name            AS collection,
  jc.metal_purity     AS karat,
  jc.metal_colour,
  jc.size_label,
  jc.diamond_quality,
  jc.measured_gross_wt_gm,
  b.net_metal_wt_gm,
  b.bom_weight_gm,
  ROUND(jc.measured_gross_wt_gm - b.bom_weight_gm, 3) AS weight_diff_gm,
  jc.length_mm, jc.breadth_mm, jc.height_mm,
  jc.stock_state,
  l.code              AS location_code,
  l.name              AS location,
  jc.received_on, jc.disposed_on,
  jc.huid, jc.hallmarked_on, jc.hallmark_centre,
  b.version_no        AS bom_version,
  b.reason            AS bom_reason,
  CASE WHEN app.has_cap('sale')
       THEN app.live_sale_price(jc.jewel_code_id) END    AS sale_price,
  CASE WHEN app.has_cap('sale')
       THEN app.alloy_sale_rate(jc.metal_purity) END     AS gold_rate_used,
  CASE WHEN app.has_cap('sale')
       THEN (SELECT value FROM app.system_setting WHERE key='pure_gold_rate_as_on') END AS price_as_on,
  CASE WHEN app.has_cap('cost')   THEN b.total_cost_price END  AS cost_price,
  CASE WHEN app.has_cap('margin')
       THEN app.live_sale_price(jc.jewel_code_id) - b.total_cost_price END AS margin,
  CASE WHEN app.has_cap('vendor') THEN v.code END        AS vendor_code,
  CASE WHEN app.has_cap('vendor') THEN v.name END        AS vendor_name,
  CASE WHEN app.has_cap('vendor') THEN v.avg_tat_days END AS vendor_avg_tat_days,
  jc.on_website, jc.website_url, jc.remarks, jc.updated_at
FROM app.jewel_code jc
JOIN app.style s        ON s.style_id = jc.style_id
JOIN app.category c     ON c.category_id = s.category_id
LEFT JOIN app.collection col ON col.collection_id = s.collection_id
LEFT JOIN app.location l     ON l.location_id = jc.location_id
LEFT JOIN app.vendor v       ON v.vendor_id = jc.vendor_id
LEFT JOIN app.bom_version b  ON b.jewel_code_id = jc.jewel_code_id AND b.is_current
WHERE jc.location_id IS NULL OR jc.location_id IN (SELECT app.visible_locations());
CREATE OR REPLACE VIEW api.sale_breakup AS
SELECT
  jc.jewel_code,
  b.version_no AS bom_version,
  CASE m.mat_class
    WHEN 'DIAMOND' THEN 'Diamonds' WHEN 'POLKI' THEN 'Polki'
    WHEN 'COLOUR_STONE' THEN 'Coloured stones' WHEN 'PEARL' THEN 'Pearls'
    WHEN 'METAL' THEN 'Gold ' || jc.metal_purity
    WHEN 'LABOUR' THEN 'Making charge' ELSE 'Other' END AS component,
  CASE WHEN m.mat_class IN ('METAL','LABOUR','FINDING') THEN NULL
       ELSE SUM(l.pcs) END                              AS pcs,
  SUM(l.qty_value)                                      AS qty,
  MAX(l.qty_uom::text)                                  AS uom,
  SUM(ROUND(CASE
    WHEN m.mat_class='METAL' THEN app.alloy_sale_rate(jc.metal_purity)*COALESCE(l.qty_value,0)
    ELSE COALESCE(l.sale_amount,0) END, 0))              AS amount
FROM app.jewel_material_line l
JOIN app.material m       ON m.material_id = l.material_id
JOIN app.bom_version b    ON b.jewel_code_id = l.jewel_code_id
                          AND b.version_no = l.version_no AND b.is_current
JOIN app.jewel_code jc    ON jc.jewel_code_id = l.jewel_code_id
WHERE app.has_cap('sale') AND app.has_cap('materials')
GROUP BY jc.jewel_code, b.version_no, m.mat_class, jc.metal_purity;
CREATE OR REPLACE VIEW api.bom_line AS
SELECT
  jc.jewel_code, l.version_no, bv.reason AS version_reason, bv.is_current,
  l.line_no, m.item_code AS material_code, m.item_name AS material_name,
  m.mat_class AS material_class, l.size_band, l.pcs, l.qty_value, l.qty_uom, l.basis,
  CASE WHEN app.has_cap('cost') THEN l.cost_rate END   AS cost_rate,
  CASE WHEN app.has_cap('cost') THEN l.cost_amount END AS cost_amount,
  CASE WHEN app.has_cap('sale') THEN
    CASE WHEN m.mat_class='METAL' THEN app.alloy_sale_rate(jc.metal_purity)
         ELSE l.sale_rate END END                        AS sale_rate,
  CASE WHEN app.has_cap('sale') THEN
    CASE WHEN m.mat_class='METAL'
         THEN ROUND(app.alloy_sale_rate(jc.metal_purity)*COALESCE(l.qty_value,0),0)
         ELSE l.sale_amount END END                      AS sale_amount
FROM app.jewel_material_line l
JOIN app.jewel_code jc  ON jc.jewel_code_id = l.jewel_code_id
JOIN app.material m     ON m.material_id = l.material_id
JOIN app.bom_version bv ON bv.jewel_code_id = l.jewel_code_id AND bv.version_no = l.version_no
WHERE app.has_cap('materials')
  AND (jc.location_id IS NULL OR jc.location_id IN (SELECT app.visible_locations()));
CREATE OR REPLACE VIEW api.stock_summary AS
SELECT COALESCE(l.name,'(unassigned)') AS location,
  COUNT(*) FILTER (WHERE jc.stock_state='IN_STOCK')    AS in_stock,
  COUNT(*) FILTER (WHERE jc.stock_state='RESERVED')    AS reserved,
  COUNT(*) FILTER (WHERE jc.stock_state='ON_APPROVAL') AS on_approval,
  COUNT(*) FILTER (WHERE jc.stock_state='IN_REPAIR')   AS in_repair,
  CASE WHEN app.has_cap('cost')
       THEN SUM(COALESCE(b.total_cost_price,0)) END    AS stock_value_at_cost,
  COUNT(*) FILTER (WHERE b.total_cost_price IS NULL)   AS unpriced_pieces
FROM app.jewel_code jc
LEFT JOIN app.location l    ON l.location_id = jc.location_id
LEFT JOIN app.bom_version b ON b.jewel_code_id = jc.jewel_code_id AND b.is_current
WHERE jc.stock_state NOT IN ('SOLD','MELTED','LOST','NOT_RECEIVED')
  AND (jc.location_id IS NULL OR jc.location_id IN (SELECT app.visible_locations()))
GROUP BY l.name;
CREATE OR REPLACE VIEW api.movement AS
SELECT jc.jewel_code, mv.move_type, fl.name AS from_location, tl.name AS to_location,
       mv.resulting_state, mv.moved_at, mv.reason, u.username AS by_user
FROM app.stock_movement mv
JOIN app.jewel_code jc  ON jc.jewel_code_id = mv.jewel_code_id
LEFT JOIN app.location fl ON fl.location_id = mv.from_location_id
LEFT JOIN app.location tl ON tl.location_id = mv.to_location_id
LEFT JOIN app.app_user u  ON u.user_id = mv.user_id
WHERE jc.location_id IS NULL OR jc.location_id IN (SELECT app.visible_locations());
CREATE OR REPLACE VIEW api.audit_log AS
SELECT a.changed_at, u.username, r.name AS role, a.action, a.table_name, a.record_pk,
       a.detail, a.export_id, a.row_count, a.ip, a.user_agent
FROM app.activity_log a
LEFT JOIN app.app_user u ON u.user_id = a.user_id
LEFT JOIN app.role r     ON r.role_id = u.role_id
WHERE app.is_admin();
CREATE OR REPLACE VIEW api.me AS
SELECT u.user_id, u.username, u.full_name, r.code AS role_code, r.name AS role_name,
       r.can_view_cost_price AS cap_cost, r.can_view_sale_price AS cap_sale,
       r.can_view_material_breakup AS cap_materials, r.can_view_vendor AS cap_vendor,
       r.can_view_margin AS cap_margin, r.can_melt AS cap_melt,
       r.can_edit_bom AS cap_edit_bom, r.can_adjust_stock AS cap_adjust,
       l.code AS home_location,
       (SELECT array_agg(m.module_code ORDER BY m.sort_order)
          FROM app.role_module_permission p JOIN app.module m USING (module_code)
         WHERE p.role_id = r.role_id AND p.can_view) AS visible_tabs
FROM app.app_user u
JOIN app.role r USING (role_id)
LEFT JOIN app.location l ON l.location_id = u.home_location_id
WHERE u.auth_uid = auth.uid();
GRANT SELECT ON ALL TABLES IN SCHEMA api TO authenticated;;
