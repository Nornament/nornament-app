
-- The first seed used DISTINCT ON with a meaningless ORDER BY, so it took an
-- arbitrary line's rate while the note claimed "most used". Reseed properly:
-- the most frequently occurring cost/sale pair per material and size band,
-- breaking ties on the higher sale rate.

DELETE FROM app.rate_chart_line
 WHERE chart_id = (SELECT chart_id FROM app.rate_chart WHERE is_default);

WITH counted AS (
  SELECT l.material_id, COALESCE(l.size_band,'') AS size_band,
         l.cost_rate, l.sale_rate, l.qty_uom::text AS uom,
         count(*) AS times
    FROM app.jewel_material_line l
    JOIN app.material m USING (material_id)
   WHERE m.mat_class <> 'METAL'
     AND l.cost_rate IS NOT NULL
   GROUP BY 1,2,3,4,5
), ranked AS (
  SELECT *, row_number() OVER (PARTITION BY material_id, size_band
                               ORDER BY times DESC, sale_rate DESC NULLS LAST) AS rn
    FROM counted
)
INSERT INTO app.rate_chart_line (chart_id, material_id, size_band, cost_rate, sale_rate, rate_uom)
SELECT (SELECT chart_id FROM app.rate_chart WHERE is_default),
       material_id, size_band, cost_rate, sale_rate, uom
  FROM ranked WHERE rn = 1;

UPDATE app.rate_chart
   SET note = 'Seeded from your pieces: the most frequently used cost and sale '
              'rate for each material and size band. Where a material was priced '
              'differently on different pieces, those lines are marked off-chart.'
 WHERE is_default;

-- mark lines that disagree with the chart, so they are findable
UPDATE app.jewel_material_line l
   SET off_chart = true
  FROM app.rate_chart_line cl, app.material m
 WHERE m.material_id = l.material_id
   AND m.mat_class <> 'METAL'
   AND cl.chart_id = (SELECT chart_id FROM app.rate_chart WHERE is_default)
   AND cl.material_id = l.material_id
   AND cl.size_band = COALESCE(l.size_band,'')
   AND (l.cost_rate IS DISTINCT FROM cl.cost_rate
     OR l.sale_rate IS DISTINCT FROM cl.sale_rate);
;
