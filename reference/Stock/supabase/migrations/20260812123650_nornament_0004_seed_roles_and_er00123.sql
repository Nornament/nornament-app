SET search_path TO app, public;

INSERT INTO module (module_code,name,sort_order) VALUES
 ('DESIGN_LIBRARY','Design Library',10),('JEWEL_CODE','Jewel Codes',20),('MEDIA','Photos & Videos',30),
 ('COSTING','Costing & BOM',40),('PRICING','Sale Pricing',50),('STOCK','Stock',60),
 ('STOCK_COUNT','Physical Stock Count',65),('TRANSFER','Transfers',70),('SALES','Sales',80),
 ('REPAIR','Repairs',85),('MELT','Melt',88),('CATALOGUE','Catalogue',90),('PRODUCTION','Job Cards',100),
 ('VENDOR','Vendors',110),('REPORTS','Reports & Margin',120),('DATA','Import / Export',125),
 ('AUDIT','Audit Log',128),('ADMIN','Users & Settings',130);

INSERT INTO role (code,name,description,can_view_cost_price,can_view_sale_price,
  can_view_material_breakup,can_view_vendor,can_view_margin,can_melt,can_edit_bom,can_adjust_stock,is_system) VALUES
 ('ADMIN','Admin / Owner','Full access. Only role that may melt.',TRUE,TRUE,TRUE,TRUE,TRUE,TRUE,TRUE,TRUE,TRUE),
 ('ACCOUNTS','Accounts','Costing and valuation.',TRUE,TRUE,TRUE,TRUE,TRUE,FALSE,TRUE,TRUE,FALSE),
 ('SALES','Sales / Showroom','Sale price and availability. Cost hidden.',FALSE,TRUE,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('GRAPHIC','Graphic / Media','Media only.',FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE,FALSE),
 ('PRODUCTION','Production','Job cards and repairs. No pricing.',FALSE,FALSE,TRUE,TRUE,FALSE,FALSE,TRUE,FALSE,FALSE);

INSERT INTO role_module_permission (role_id,module_code,can_view,can_create,can_edit,can_delete,can_export)
SELECT r.role_id,m.module_code,TRUE,TRUE,TRUE,TRUE,TRUE FROM role r CROSS JOIN module m WHERE r.code='ADMIN';
INSERT INTO role_module_permission (role_id,module_code,can_view,can_export)
SELECT r.role_id,m.module_code,TRUE,FALSE FROM role r CROSS JOIN module m
WHERE r.code='SALES' AND m.module_code IN ('DESIGN_LIBRARY','JEWEL_CODE','MEDIA','PRICING','STOCK','STOCK_COUNT','SALES','CATALOGUE');
INSERT INTO role_module_permission (role_id,module_code,can_view,can_edit,can_export)
SELECT r.role_id,m.module_code,TRUE,TRUE,TRUE FROM role r CROSS JOIN module m
WHERE r.code='ACCOUNTS' AND m.module_code IN ('DESIGN_LIBRARY','JEWEL_CODE','MEDIA','COSTING','PRICING','STOCK','STOCK_COUNT','TRANSFER','SALES','REPAIR','CATALOGUE','PRODUCTION','VENDOR','REPORTS');
INSERT INTO role_module_permission (role_id,module_code,can_view,can_create,can_edit,can_delete,can_export)
SELECT r.role_id,m.module_code,TRUE,TRUE,TRUE,TRUE,TRUE FROM role r CROSS JOIN module m
WHERE r.code='GRAPHIC' AND m.module_code='MEDIA';
INSERT INTO role_module_permission (role_id,module_code,can_view)
SELECT r.role_id,m.module_code,TRUE FROM role r CROSS JOIN module m
WHERE r.code='GRAPHIC' AND m.module_code IN ('DESIGN_LIBRARY','JEWEL_CODE');
INSERT INTO role_module_permission (role_id,module_code,can_view,can_create,can_edit,can_export)
SELECT r.role_id,m.module_code,TRUE,TRUE,TRUE,TRUE FROM role r CROSS JOIN module m
WHERE r.code='PRODUCTION' AND m.module_code IN ('REPAIR','PRODUCTION');
INSERT INTO role_module_permission (role_id,module_code,can_view)
SELECT r.role_id,m.module_code,TRUE FROM role r CROSS JOIN module m
WHERE r.code='PRODUCTION' AND m.module_code IN ('DESIGN_LIBRARY','JEWEL_CODE','MEDIA','STOCK','VENDOR');

INSERT INTO location (code,name,kind,city) VALUES
 ('HO','Head Office','GODOWN','Jaipur'),('MUM','Mumbai','SHOWROOM','Mumbai'),
 ('KOL','Kolkata','SHOWROOM','Kolkata'),('WS1','Workshop','WORKSHOP','Jaipur');

INSERT INTO app_user (username,full_name,email,auth_uid,role_id,home_location_id,must_change_password) VALUES
 ('pradhyuman','Pradhyuman','pradhyuman@karigar.live','fda6fe50-cff2-4c32-8f99-da40d25f8cfc',
   (SELECT role_id FROM role WHERE code='ADMIN'), NULL, FALSE),
 ('connect','Nornament Connect','connect@karigar.live','5cf533f2-54fb-4267-af32-ca91a14405de',
   (SELECT role_id FROM role WHERE code='ADMIN'), NULL, FALSE);

INSERT INTO category (code,name,code_prefix,sort_order) VALUES
 ('EARR','Earrings','ER',10),('NECK','Necklaces','NK',20),('RING','Rings','RG',30),
 ('BANG','Bangles / Bracelets','BG',40),('BROO','Brooch','BC',50),
 ('MANG','Mangalsutras / Chains','MG',60),('PEND','Pendant Sets','PS',70);

INSERT INTO material (item_code,item_name,mat_class,default_uom) VALUES
 ('DRKL SI-I','Diamond RKL SI-I','DIAMOND','CT'),('DTBFGH VS-SI','Diamond TBFGH VS-SI','DIAMOND','CT'),
 ('FPL','Foil Polki','POLKI','CT'),('G','Gold','METAL','GM'),('GC','Gold Chakri','METAL','GM'),
 ('SP01RG','Stone Semi Precious 01RG','COLOUR_STONE','CT'),('MAKING','Making Charge','LABOUR','GM');

INSERT INTO rate_card (code,card_type,effective_from,notes) VALUES
 ('COST-2026-03','COST',DATE '2026-03-01','Frozen cost rates from the ER00123 job card'),
 ('SALE-2026-03','SALE',DATE '2026-03-01','Policy sale rates for stones and making');

INSERT INTO rate_card_line (rate_card_id,material_id,size_band,rate,rate_uom)
SELECT (SELECT rate_card_id FROM rate_card WHERE code='COST-2026-03'),m.material_id,v.b,v.r,v.u::uom
FROM (VALUES
 ('DRKL SI-I','+2',8500.0,'CT'),('DTBFGH VS-SI','-2BG',26000.0,'CT'),('FPL','+24-36',9000.0,'CT'),
 ('FPL','+36-44',12000.0,'CT'),('G','',4093.0,'GM'),('GC','',4093.0,'GM'),
 ('SP01RG','',500.0,'CT'),('MAKING','',1000.0,'GM')) AS v(c,b,r,u) JOIN material m ON m.item_code=v.c;
INSERT INTO rate_card_line (rate_card_id,material_id,size_band,rate,rate_uom)
SELECT (SELECT rate_card_id FROM rate_card WHERE code='SALE-2026-03'),m.material_id,v.b,v.r,v.u::uom
FROM (VALUES
 ('DRKL SI-I','+2',20000.0,'CT'),('DTBFGH VS-SI','-2BG',50000.0,'CT'),('FPL','+24-36',23000.0,'CT'),
 ('FPL','+36-44',40000.0,'CT'),('G','',8699.0,'GM'),('GC','',8699.0,'GM'),
 ('SP01RG','',7000.0,'CT'),('MAKING','',1500.0,'GM')) AS v(c,b,r,u) JOIN material m ON m.item_code=v.c;

INSERT INTO style (style_code,name,category_id,state,designed_on,nos_min_qty)
SELECT 'ER00135','Emerald floral polki earring',category_id,'IN_STOCK_DESIGN',DATE '2026-03-31',3
FROM category WHERE code='EARR';

INSERT INTO jewel_code (jewel_code,style_id,metal_purity,metal_colour,diamond_quality,
  measured_gross_wt_gm,fg_date,huid,stock_state,location_id,received_on)
SELECT 'ER00123',s.style_id,'14K','Yellow','VS-SI',12.370,DATE '2026-03-31','HU7X4K','IN_STOCK',
  (SELECT location_id FROM location WHERE code='MUM'),DATE '2026-04-02'
FROM style s WHERE s.style_code='ER00135';

INSERT INTO bom_version (jewel_code_id,version_no,reason,note,cost_rate_card_id,sale_rate_card_id,is_current)
SELECT jewel_code_id,1,'INITIAL','As per the original printed job card',
  (SELECT rate_card_id FROM rate_card WHERE code='COST-2026-03'),
  (SELECT rate_card_id FROM rate_card WHERE code='SALE-2026-03'),TRUE
FROM jewel_code WHERE jewel_code='ER00123';

INSERT INTO jewel_material_line
 (jewel_code_id,version_no,line_no,material_id,size_band,pcs,qty_value,qty_uom,basis,cost_rate,sale_rate)
SELECT jc.jewel_code_id,1,v.ln,m.material_id,v.b,v.p,v.q,v.u::uom,v.bs::charge_basis,v.cr,v.sr
FROM (VALUES
 (1,'DRKL SI-I','+2',10,0.09,'CT','BY_QTY',8500.0,20000.0),
 (2,'DTBFGH VS-SI','-2BG',56,0.40,'CT','BY_QTY',26000.0,50000.0),
 (3,'FPL','+24-36',16,4.97,'CT','BY_QTY',9000.0,23000.0),
 (4,'FPL','+36-44',2,0.74,'CT','BY_QTY',12000.0,40000.0),
 (5,'G','',NULL,9.51,'GM','BY_QTY',4093.0,8699.0),
 (6,'GC','',10,0.34,'GM','BY_QTY',4093.0,8699.0),
 (7,'SP01RG','',2,6.40,'CT','BY_QTY',500.0,7000.0),
 (8,'MAKING','',NULL,NULL,'GM','BY_NET_METAL_WT',1000.0,1500.0)
) AS v(ln,c,b,p,q,u,bs,cr,sr)
JOIN material m ON m.item_code=v.c
CROSS JOIN jewel_code jc WHERE jc.jewel_code='ER00123';

SELECT recost_jewel(jewel_code_id,1,NULL) FROM jewel_code WHERE jewel_code='ER00123';

INSERT INTO stock_movement (jewel_code_id,move_type,to_location_id,resulting_state,reference_no)
SELECT jewel_code_id,'RECEIPT',location_id,'IN_STOCK','GRN-0001' FROM jewel_code WHERE jewel_code='ER00123';;
