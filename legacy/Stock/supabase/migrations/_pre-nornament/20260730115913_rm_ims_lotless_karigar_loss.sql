ALTER TABLE rm_txns DROP CONSTRAINT IF EXISTS lot_required;
ALTER TABLE rm_txns ADD CONSTRAINT lot_required
  CHECK (lot_id IS NOT NULL OR txn_type IN ('FINISHED_IN','LOSS_OUT'));;
