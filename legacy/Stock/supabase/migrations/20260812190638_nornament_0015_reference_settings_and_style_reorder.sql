-- The one app needs a little more reference data to draw its own screens:
-- the live pure gold rate (so prices recompute in the browser exactly as the
-- database computes them) and each design's reorder floor.
CREATE OR REPLACE VIEW api.reference AS
SELECT 'category' AS kind, code, name AS label, NULL::text AS extra, sort_order AS ord
  FROM app.category
UNION ALL
SELECT 'location', code, name, kind, location_id FROM app.location WHERE is_active
UNION ALL
SELECT 'karat', karat, karat, sale_factor::text, 0 FROM app.metal_purity
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
       (SELECT c.name FROM app.category c WHERE c.category_id = s.category_id)
         || '|' || s.nos_min_qty, style_id
  FROM app.style s WHERE is_active
UNION ALL
-- only the two settings the front end has to agree with; nothing else leaks
SELECT 'setting', key, value, NULL, 0 FROM app.system_setting
 WHERE key IN ('pure_gold_rate','pure_gold_rate_as_on','line_rounding_dp')
   AND app.has_cap('sale')
UNION ALL
SELECT 'rate', m.item_code || '|' || l.size_band,
       l.rate::text, c.card_type, 0
  FROM app.rate_card_line l
  JOIN app.rate_card c USING (rate_card_id)
  JOIN app.material m USING (material_id)
 WHERE (c.card_type = 'COST' AND app.has_cap('cost'))
    OR (c.card_type = 'SALE' AND app.has_cap('sale'));

GRANT SELECT ON api.reference TO authenticated;;
