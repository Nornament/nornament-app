-- The api views as the real migrations define them: every sensitive column
-- wrapped in app.has_cap(), which is exactly what the golden shim defeats.
CREATE SCHEMA IF NOT EXISTS api;

CREATE OR REPLACE FUNCTION app.has_cap(p_cap TEXT) RETURNS boolean
LANGUAGE sql STABLE AS $$ SELECT false $$;

CREATE OR REPLACE FUNCTION app.line_weight_gm(p_qty NUMERIC, p_uom TEXT) RETURNS NUMERIC
LANGUAGE sql IMMUTABLE AS $$
  SELECT COALESCE(p_qty,0) * CASE p_uom WHEN 'GM' THEN 1.0 WHEN 'CT' THEN 0.2
                                        WHEN 'RATTI' THEN 0.1215 ELSE 0.0 END $$;

CREATE OR REPLACE FUNCTION app.metal_rate(p_karat TEXT, p_side TEXT DEFAULT 'SALE') RETURNS NUMERIC
LANGUAGE sql STABLE AS $$
  SELECT round(m.pure_rate * CASE WHEN upper(p_side)='COST' THEN mp.true_fineness ELSE mp.sale_factor END)
    FROM app.metal_purity mp JOIN app.metal m ON m.code = mp.metal WHERE mp.karat = p_karat $$;

CREATE OR REPLACE FUNCTION app.live_sale_price(p_jc INT) RETURNS NUMERIC
LANGUAGE sql STABLE AS $$
  WITH v AS (SELECT current_bom_version AS n, metal_purity AS karat FROM app.jewel_code WHERE jewel_code_id=p_jc),
  metal AS (SELECT COALESCE(SUM(app.line_weight_gm(l.qty_value,l.qty_uom)),0) AS gm
              FROM app.jewel_material_line l JOIN app.material m USING (material_id), v
             WHERE l.jewel_code_id=p_jc AND l.version_no=v.n AND m.mat_class='METAL')
  SELECT COALESCE(SUM(ROUND(CASE
      WHEN m.mat_class='METAL' THEN app.metal_rate(v.karat,'SALE') * COALESCE(l.qty_value,0)
      WHEN l.basis='BY_NET_METAL_WT' THEN COALESCE(l.sale_rate,0) * (SELECT gm FROM metal)
      WHEN l.basis='BY_PIECE' THEN COALESCE(l.sale_rate,0) * COALESCE(l.pcs,0)
      WHEN l.basis='FLAT' THEN COALESCE(l.sale_rate,0)
      ELSE COALESCE(l.sale_rate,0) * COALESCE(l.qty_value,0) END, 0)),0)
    FROM app.jewel_material_line l JOIN app.material m USING (material_id), v
   WHERE l.jewel_code_id=p_jc AND l.version_no=v.n $$;

CREATE OR REPLACE FUNCTION app.current_cost(p_jc INT) RETURNS NUMERIC
LANGUAGE sql STABLE AS $$
  WITH v AS (SELECT current_bom_version AS n, metal_purity AS karat FROM app.jewel_code WHERE jewel_code_id=p_jc),
  metal AS (SELECT COALESCE(SUM(app.line_weight_gm(l.qty_value,l.qty_uom)),0) AS gm
              FROM app.jewel_material_line l JOIN app.material m USING (material_id), v
             WHERE l.jewel_code_id=p_jc AND l.version_no=v.n AND m.mat_class='METAL')
  SELECT COALESCE(SUM(ROUND(CASE
      WHEN m.mat_class='METAL' THEN app.metal_rate(v.karat,'COST') * COALESCE(l.qty_value,0)
      WHEN l.basis='BY_NET_METAL_WT' THEN COALESCE(l.cost_rate,0) * (SELECT gm FROM metal)
      WHEN l.basis='BY_PIECE' THEN COALESCE(l.cost_rate,0) * COALESCE(l.pcs,0)
      WHEN l.basis='FLAT' THEN COALESCE(l.cost_rate,0)
      ELSE COALESCE(l.cost_rate,0) * COALESCE(l.qty_value,0) END, 0)),0)
    FROM app.jewel_material_line l JOIN app.material m USING (material_id), v
   WHERE l.jewel_code_id=p_jc AND l.version_no=v.n $$;

CREATE VIEW api.jewel AS
SELECT jc.jewel_code_id, jc.jewel_code, s.style_code, jc.metal_purity AS karat,
       jc.measured_gross_wt_gm, b.net_metal_wt_gm, b.bom_weight_gm, jc.stock_state,
       CASE WHEN app.has_cap('sale') THEN app.live_sale_price(jc.jewel_code_id) END AS sale_price,
       CASE WHEN app.has_cap('cost') THEN b.total_cost_price END AS cost_price,
       CASE WHEN app.has_cap('cost') THEN app.current_cost(jc.jewel_code_id) END AS current_cost,
       CASE WHEN app.has_cap('margin')
            THEN app.live_sale_price(jc.jewel_code_id) - b.total_cost_price END AS margin
  FROM app.jewel_code jc
  JOIN app.style s ON s.style_id = jc.style_id
  LEFT JOIN app.bom_version b ON b.jewel_code_id = jc.jewel_code_id AND b.is_current;

CREATE VIEW api.bom_line AS
SELECT jc.jewel_code, l.version_no, l.line_no, m.item_code AS material, l.qty_value, l.qty_uom,
       CASE WHEN app.has_cap('cost') THEN l.cost_amount END AS cost_amount,
       CASE WHEN app.has_cap('sale') THEN l.sale_amount END AS sale_amount
  FROM app.jewel_material_line l
  JOIN app.jewel_code jc USING (jewel_code_id)
  JOIN app.material m USING (material_id);

CREATE VIEW api.stock_summary AS
SELECT l.code AS location, count(*) AS pieces
  FROM app.jewel_code jc JOIN app.location l USING (location_id)
 WHERE jc.stock_state IN ('IN_STOCK','RESERVED') GROUP BY l.code;

CREATE VIEW api.stock_count AS
SELECT sc.count_id, sc.count_ref, sc.status, sc.result FROM app.stock_count sc;
