-- ============================================================
-- 0026  Making charged as a fixed amount.
--
-- FLAT has always been in the schema but nothing computed it:
-- recost_jewel handled BY_QTY, BY_NET_METAL_WT and BY_PIECE and
-- skipped FLAT entirely, so a fixed making charge saved happily
-- and then contributed ZERO to the piece. That is the worst kind
-- of bug - it looks like it worked.
--
-- On a FLAT line the rate IS the amount. No quantity, no
-- multiplication. Imports are untouched: Gati keeps arriving as a
-- per-gram rate on net metal weight. FLAT is only what you pick
-- in the BOM editor.
-- ============================================================
SET search_path TO app, public;

CREATE OR REPLACE FUNCTION app.recost_jewel(p_jc integer, p_version integer DEFAULT NULL::integer,
                                            p_user integer DEFAULT NULL::integer)
RETURNS void LANGUAGE plpgsql SET search_path TO 'app', 'public' AS $function$
DECLARE
  v INT := COALESCE(p_version,(SELECT current_bom_version FROM jewel_code WHERE jewel_code_id=p_jc));
  v_metal NUMERIC;
  ldp INT := setting_int('line_rounding_dp',0);
  tdp INT := setting_int('total_rounding_dp',0);
BEGIN
  SELECT COALESCE(SUM(line_weight_gm(l.qty_value,l.qty_uom)),0) INTO v_metal
  FROM jewel_material_line l JOIN material m USING (material_id)
  WHERE l.jewel_code_id=p_jc AND l.version_no=v AND m.mat_class='METAL';

  UPDATE jewel_material_line l SET qty_value=v_metal, qty_uom='GM',
      cost_amount=ROUND(COALESCE(l.cost_rate,0)*v_metal,ldp),
      sale_amount=ROUND(COALESCE(l.sale_rate,0)*v_metal,ldp)
    WHERE l.jewel_code_id=p_jc AND l.version_no=v AND l.basis='BY_NET_METAL_WT';

  UPDATE jewel_material_line l
     SET cost_amount=ROUND(COALESCE(l.cost_rate,0)*COALESCE(l.qty_value,0),ldp),
         sale_amount=ROUND(COALESCE(l.sale_rate,0)*COALESCE(l.qty_value,0),ldp)
    WHERE l.jewel_code_id=p_jc AND l.version_no=v AND l.basis='BY_QTY';

  UPDATE jewel_material_line l
     SET cost_amount=ROUND(COALESCE(l.cost_rate,0)*COALESCE(l.pcs,0),ldp),
         sale_amount=ROUND(COALESCE(l.sale_rate,0)*COALESCE(l.pcs,0),ldp)
    WHERE l.jewel_code_id=p_jc AND l.version_no=v AND l.basis='BY_PIECE';

  -- NEW: a fixed amount is not multiplied by anything.
  UPDATE jewel_material_line l
     SET cost_amount=ROUND(COALESCE(l.cost_rate,0),ldp),
         sale_amount=ROUND(COALESCE(l.sale_rate,0),ldp)
    WHERE l.jewel_code_id=p_jc AND l.version_no=v AND l.basis='FLAT';

  UPDATE bom_version b SET
    net_metal_wt_gm = v_metal,
    bom_weight_gm = (SELECT COALESCE(SUM(line_weight_gm(l.qty_value,l.qty_uom)),0)
                       FROM jewel_material_line l JOIN material m USING (material_id)
                      WHERE l.jewel_code_id=p_jc AND l.version_no=v AND m.mat_class<>'LABOUR'),
    total_cost_price = ROUND((SELECT COALESCE(SUM(cost_amount),0) FROM jewel_material_line
                               WHERE jewel_code_id=p_jc AND version_no=v),tdp),
    total_sale_price = ROUND((SELECT COALESCE(SUM(sale_amount),0) FROM jewel_material_line
                               WHERE jewel_code_id=p_jc AND version_no=v),tdp),
    making_value = ROUND((SELECT COALESCE(SUM(l.sale_amount),0) FROM jewel_material_line l
                            JOIN material m USING (material_id)
                           WHERE l.jewel_code_id=p_jc AND l.version_no=v AND m.mat_class='LABOUR'),tdp),
    goods_value  = ROUND((SELECT COALESCE(SUM(l.sale_amount),0) FROM jewel_material_line l
                            JOIN material m USING (material_id)
                           WHERE l.jewel_code_id=p_jc AND l.version_no=v AND m.mat_class<>'LABOUR'),tdp)
  WHERE b.jewel_code_id=p_jc AND b.version_no=v;
END $function$;

CREATE OR REPLACE FUNCTION app.live_sale_price(p_jc INT, p_version INT DEFAULT NULL)
RETURNS NUMERIC LANGUAGE sql STABLE SECURITY DEFINER SET search_path = app, public AS $$
  WITH v AS (
    SELECT COALESCE(p_version,(SELECT current_bom_version FROM jewel_code WHERE jewel_code_id=p_jc)) AS n,
           (SELECT metal_purity FROM jewel_code WHERE jewel_code_id=p_jc) AS karat),
  metal AS (
    SELECT COALESCE(SUM(line_weight_gm(l.qty_value,l.qty_uom)),0) AS gm
    FROM jewel_material_line l JOIN material m USING (material_id), v
    WHERE l.jewel_code_id=p_jc AND l.version_no=v.n AND m.mat_class='METAL')
  SELECT COALESCE(SUM(ROUND(
    CASE
      WHEN m.mat_class='METAL'  THEN app.alloy_sale_rate(v.karat) * COALESCE(l.qty_value,0)
      WHEN l.basis='BY_NET_METAL_WT' THEN COALESCE(l.sale_rate,0) * (SELECT gm FROM metal)
      WHEN l.basis='BY_PIECE'   THEN COALESCE(l.sale_rate,0) * COALESCE(l.pcs,0)
      WHEN l.basis='FLAT'       THEN COALESCE(l.sale_rate,0)   -- the rate is the amount
      ELSE COALESCE(l.sale_rate,0) * COALESCE(l.qty_value,0)
    END, setting_int('line_rounding_dp',0))),0)
  FROM jewel_material_line l JOIN material m USING (material_id), v
  WHERE l.jewel_code_id=p_jc AND l.version_no=v.n;
$$;;
