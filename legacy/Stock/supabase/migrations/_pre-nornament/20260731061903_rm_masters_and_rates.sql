-- material list becomes admin-editable (app masters), drop rigid check
ALTER TABLE rm_lots DROP CONSTRAINT IF EXISTS rm_lots_material_check;

-- seed masters + rates in settings (no-op if present)
INSERT INTO settings (key, value) VALUES
('rm_materials', '["gold","silver","diamond","stone","other","customer_jewelry"]'),
('rm_forms', '["melting bag","casting bag","tar (wire)","sheet","chorsa","grain","findings","scrap","dust","biscuit","packet","jewellery"]'),
('rm_items', '{
  "gold":[["G999",0.999],["G995",0.995],["G22K",0.916],["G18K",0.750],["G14K",0.585],["G12K",0.500],["G9K",0.375],["G18%",0.180]],
  "silver":[["S999",0.999],["S995",0.995],["S925",0.925]],
  "diamond":[["Natural",1],["Lab Grown",1],["Polki",1]],
  "stone":[["Precious",1],["Semi-Precious",1],["Organic",1],["Synthetic",1]],
  "other":[["NA",1]],
  "customer_jewelry":[["CJ",1],["CG999",0.999],["CG995",0.995],["CG22K",0.916],["CG18K",0.750],["CG14K",0.585]]
}'),
('rm_rates', '{"gold24k":null,"silver":null,"updated":null}')
ON CONFLICT (key) DO NOTHING;;
