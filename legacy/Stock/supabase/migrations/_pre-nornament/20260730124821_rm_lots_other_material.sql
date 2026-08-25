ALTER TABLE rm_lots DROP CONSTRAINT IF EXISTS rm_lots_material_check;
ALTER TABLE rm_lots ADD CONSTRAINT rm_lots_material_check
  CHECK (material IN ('gold','silver','diamond','stone','other','jewellery','customer_jewelry'));;
