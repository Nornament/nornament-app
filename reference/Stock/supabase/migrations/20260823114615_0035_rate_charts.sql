
-- ─────────────────────────────────────────────────────────────────────────
-- 0035  Rate charts you can keep several of
--
-- The old rate_card split cost and sale into two rows per material across two
-- cards. A chart now holds both on one line, has a name, and can be the
-- default. A chart that has priced a piece is never edited in place — it
-- forks, so a quote from March still reconciles in September.
-- ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS app.rate_chart (
  chart_id     SERIAL PRIMARY KEY,
  code         TEXT NOT NULL,
  name         TEXT NOT NULL,
  version_no   INT  NOT NULL DEFAULT 1,
  is_default   BOOLEAN NOT NULL DEFAULT false,
  is_locked    BOOLEAN NOT NULL DEFAULT false,   -- true once a piece has used it
  forked_from  INT REFERENCES app.rate_chart(chart_id),
  note         TEXT,
  created_by   INT REFERENCES app.app_user(user_id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (code, version_no)
);
CREATE UNIQUE INDEX IF NOT EXISTS rate_chart_one_default
  ON app.rate_chart((is_default)) WHERE is_default;

CREATE TABLE IF NOT EXISTS app.rate_chart_line (
  chart_id    INT NOT NULL REFERENCES app.rate_chart(chart_id) ON DELETE CASCADE,
  material_id INT NOT NULL REFERENCES app.material(material_id),
  size_band   TEXT NOT NULL DEFAULT '',
  cost_rate   NUMERIC(14,4),
  sale_rate   NUMERIC(14,4),
  rate_uom    TEXT,
  PRIMARY KEY (chart_id, material_id, size_band),
  CHECK (cost_rate IS NULL OR cost_rate >= 0),
  CHECK (sale_rate IS NULL OR sale_rate >= 0)
);
COMMENT ON TABLE app.rate_chart_line IS
  'Cost and sale on one row. Metal materials are absent on purpose — their '
  'rate comes from app.metal, and a chart must never be able to override it.';

-- ── seed one chart from what the pieces already use ──────────────────────
-- The most common rate per material and band across live BOM lines is a
-- better starting point than an empty chart or a guess.
INSERT INTO app.rate_chart (code, name, is_default, note, created_by)
SELECT 'STD', 'Standard', true,
       'Seeded from the rates already on your pieces — the most-used rate per material and size', 1
WHERE NOT EXISTS (SELECT 1 FROM app.rate_chart);

INSERT INTO app.rate_chart_line (chart_id, material_id, size_band, cost_rate, sale_rate, rate_uom)
SELECT c.chart_id, x.material_id, x.size_band, x.cost_rate, x.sale_rate, x.uom
  FROM app.rate_chart c,
  LATERAL (
    SELECT DISTINCT ON (l.material_id, COALESCE(l.size_band,''))
           l.material_id, COALESCE(l.size_band,'') AS size_band,
           l.cost_rate, l.sale_rate, l.qty_uom::text AS uom
      FROM app.jewel_material_line l
      JOIN app.material m USING (material_id)
     WHERE m.mat_class <> 'METAL'
     ORDER BY l.material_id, COALESCE(l.size_band,''), l.material_id
  ) x
 WHERE c.is_default
ON CONFLICT DO NOTHING;

ALTER TABLE app.jewel_material_line
  ADD COLUMN IF NOT EXISTS off_chart BOOLEAN NOT NULL DEFAULT false;
COMMENT ON COLUMN app.jewel_material_line.off_chart IS
  'This line carries a rate that differs from the chart it was priced against '
  '— deliberate, and findable later.';

-- ── read ─────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW api.rate_chart
WITH (security_invoker = false) AS
SELECT c.chart_id, c.code, c.name, c.version_no, c.is_default, c.is_locked,
       c.note, c.created_at,
       (SELECT count(*) FROM app.rate_chart_line l WHERE l.chart_id = c.chart_id) AS lines
  FROM app.rate_chart c
 WHERE app.has_cap('cost') OR app.has_cap('sale')
 ORDER BY c.is_default DESC, c.code, c.version_no DESC;

CREATE OR REPLACE VIEW api.rate_chart_line
WITH (security_invoker = false) AS
SELECT l.chart_id, c.code AS chart_code, m.item_code AS material,
       m.item_name AS material_name, m.category, mc.name AS category_name,
       mc.sort_order AS category_order, l.size_band,
       CASE WHEN app.has_cap('cost') THEN l.cost_rate END AS cost_rate,
       CASE WHEN app.has_cap('sale') THEN l.sale_rate END AS sale_rate,
       CASE WHEN app.has_cap('cost') AND app.has_cap('sale') AND l.cost_rate > 0
            THEN round(l.sale_rate / l.cost_rate, 2) END AS multiple,
       COALESCE(l.rate_uom, m.default_uom::text) AS uom
  FROM app.rate_chart_line l
  JOIN app.rate_chart c ON c.chart_id = l.chart_id
  JOIN app.material m ON m.material_id = l.material_id
  JOIN app.material_category mc ON mc.code = m.category
 WHERE app.has_cap('cost') OR app.has_cap('sale');

GRANT SELECT ON api.rate_chart, api.rate_chart_line TO anon, authenticated;

-- ── the suggestion shown beside a rate box ───────────────────────────────
CREATE OR REPLACE FUNCTION app.chart_rate(p_material TEXT, p_band TEXT,
                                          p_side TEXT DEFAULT 'COST',
                                          p_chart INT DEFAULT NULL)
RETURNS NUMERIC
LANGUAGE sql STABLE SET search_path = app, public AS $$
  SELECT CASE WHEN upper(p_side)='COST' THEN l.cost_rate ELSE l.sale_rate END
    FROM app.rate_chart_line l
    JOIN app.material m ON m.material_id = l.material_id
   WHERE m.item_code = upper(btrim(p_material))
     AND l.size_band = COALESCE(btrim(p_band),'')
     AND l.chart_id = COALESCE(p_chart, (SELECT chart_id FROM app.rate_chart WHERE is_default))
   LIMIT 1
$$;
;
