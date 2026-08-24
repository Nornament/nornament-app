ALTER TABLE rm_lots DROP CONSTRAINT IF EXISTS rm_lots_material_check;
ALTER TABLE rm_lots ADD CONSTRAINT rm_lots_material_check
  CHECK (material IN ('gold','silver','diamond','stone','jewellery','customer_jewelry'));
ALTER TABLE rm_lots ADD COLUMN IF NOT EXISTS owner text NOT NULL DEFAULT 'house'
  CHECK (owner IN ('house','client'));
ALTER TABLE rm_lots ADD COLUMN IF NOT EXISTS client_ref text;
ALTER TABLE rm_lots ADD COLUMN IF NOT EXISTS branch text NOT NULL DEFAULT 'NRM';

ALTER TABLE rm_txns DROP CONSTRAINT IF EXISTS rm_txns_txn_type_check;
ALTER TABLE rm_txns ADD CONSTRAINT rm_txns_txn_type_check CHECK (txn_type IN (
  'PURCHASE_IN','OPENING_IN','ISSUE_OUT','FINISHED_IN','SCRAP_IN',
  'MELT_OUT','MELT_IN','CLIENT_RETURN_IN','SALE_OUT','ADJUST',
  'LOSS_OUT','LOSS_RECOVERY_IN','TRANSFER_OUT','TRANSFER_IN','CLIENT_METAL_IN'
));
ALTER TABLE rm_txns DROP CONSTRAINT IF EXISTS sign_matches_type;
ALTER TABLE rm_txns ADD CONSTRAINT sign_matches_type CHECK (
  (txn_type IN ('PURCHASE_IN','OPENING_IN','SCRAP_IN','MELT_IN','CLIENT_RETURN_IN',
                'FINISHED_IN','LOSS_RECOVERY_IN','TRANSFER_IN','CLIENT_METAL_IN') AND qty >= 0)
  OR (txn_type IN ('ISSUE_OUT','MELT_OUT','SALE_OUT','LOSS_OUT','TRANSFER_OUT') AND qty <= 0)
  OR txn_type = 'ADJUST'
);

DROP VIEW IF EXISTS v_rm_lot_balance;
CREATE VIEW v_rm_lot_balance AS
SELECT l.id, l.lot_code, l.material, l.owner, l.client_ref, l.branch,
       l.form, l.purity_label, l.fineness, l.uom,
       l.description, l.box_no, l.location, l.photos, l.status,
       coalesce(sum(t.qty),0)::numeric(12,3) AS balance,
       coalesce(sum(t.pcs),0) AS balance_pcs,
       (coalesce(sum(t.qty),0) * coalesce(l.fineness,1))::numeric(12,3) AS fine_balance,
       max(t.created_at) AS last_txn_at,
       count(t.id) AS txn_count
FROM rm_lots l LEFT JOIN rm_txns t ON t.lot_id = l.id
GROUP BY l.id;;
