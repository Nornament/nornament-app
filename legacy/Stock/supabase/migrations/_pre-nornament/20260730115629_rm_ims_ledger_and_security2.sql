CREATE OR REPLACE VIEW v_rm_party_outstanding AS
SELECT p.id, p.name, p.party_type,
  coalesce(sum(CASE WHEN t.txn_type='ISSUE_OUT' THEN -t.qty END),0)::numeric(12,3) AS issued_g,
  coalesce(sum(CASE WHEN t.txn_type IN ('FINISHED_IN','SCRAP_IN') THEN t.qty
                    WHEN t.txn_type='LOSS_OUT' THEN -t.qty END),0)::numeric(12,3) AS returned_g,
  (coalesce(sum(CASE WHEN t.txn_type='ISSUE_OUT' THEN -t.qty END),0)
   - coalesce(sum(CASE WHEN t.txn_type IN ('FINISHED_IN','SCRAP_IN') THEN t.qty
                       WHEN t.txn_type='LOSS_OUT' THEN -t.qty END),0))::numeric(12,3) AS outstanding_g,
  (coalesce(sum(CASE WHEN t.txn_type='ISSUE_OUT' THEN -t.qty * coalesce(t.fineness, l.fineness, 1) END),0)
   - coalesce(sum(CASE WHEN t.txn_type IN ('FINISHED_IN','SCRAP_IN') THEN t.qty * coalesce(t.fineness, l.fineness, 1)
                       WHEN t.txn_type='LOSS_OUT' THEN -t.qty * coalesce(t.fineness, l.fineness, 1) END),0))::numeric(12,3) AS outstanding_fine
FROM rm_parties p
LEFT JOIN rm_txns t ON t.party_id = p.id
LEFT JOIN rm_lots l ON l.id = t.lot_id
GROUP BY p.id;

DROP VIEW IF EXISTS v_rm_job_wastage;
CREATE VIEW v_rm_job_wastage AS
SELECT t.job_ref, t.party_id, p.name AS party_name,
  coalesce(sum(CASE WHEN t.txn_type='ISSUE_OUT' THEN -t.qty END),0)::numeric(12,3) AS issued_g,
  coalesce(sum(CASE WHEN t.txn_type='FINISHED_IN' THEN t.qty END),0)::numeric(12,3) AS finished_g,
  coalesce(sum(CASE WHEN t.txn_type='SCRAP_IN' THEN t.qty END),0)::numeric(12,3) AS scrap_g,
  coalesce(sum(CASE WHEN t.txn_type='LOSS_OUT' THEN -t.qty END),0)::numeric(12,3) AS loss_g,
  (coalesce(sum(CASE WHEN t.txn_type='ISSUE_OUT' THEN -t.qty END),0)
   - coalesce(sum(CASE WHEN t.txn_type='FINISHED_IN' THEN t.qty END),0)
   - coalesce(sum(CASE WHEN t.txn_type='SCRAP_IN' THEN t.qty END),0)
   - coalesce(sum(CASE WHEN t.txn_type='LOSS_OUT' THEN -t.qty END),0))::numeric(12,3) AS wastage_g
FROM rm_txns t LEFT JOIN rm_parties p ON p.id = t.party_id
WHERE t.job_ref IS NOT NULL
GROUP BY t.job_ref, t.party_id, p.name;

ALTER VIEW v_rm_lot_balance SET (security_invoker = true);
ALTER VIEW v_rm_party_outstanding SET (security_invoker = true);
ALTER VIEW v_rm_job_wastage SET (security_invoker = true);
GRANT SELECT ON v_rm_job_wastage TO authenticated;;
