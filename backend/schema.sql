CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, label TEXT NOT NULL, url TEXT,
 scope TEXT, period TEXT, status TEXT, detail TEXT, fetchedAt TEXT);
CREATE TABLE IF NOT EXISTS authorities(id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT,
 branch TEXT, sphere TEXT, institution TEXT, uf TEXT, party TEXT, sourceId TEXT REFERENCES sources(id), sourceUrl TEXT,
 position TEXT, employmentStatus TEXT, positionCount INTEGER DEFAULT 1, positions TEXT, searchText TEXT);
CREATE TABLE IF NOT EXISTS suppliers(key TEXT PRIMARY KEY, name TEXT NOT NULL, cnpj TEXT);
CREATE TABLE IF NOT EXISTS expenses(id TEXT PRIMARY KEY, authorityId TEXT NOT NULL REFERENCES authorities(id),
 sourceId TEXT NOT NULL REFERENCES sources(id), date TEXT, year INTEGER NOT NULL, month INTEGER NOT NULL,
 category TEXT, amountCents INTEGER NOT NULL, documentId TEXT, documentUrl TEXT,
 supplierKey TEXT REFERENCES suppliers(key), kind TEXT NOT NULL, firstSeen TEXT NOT NULL, lastChanged TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS expense_authority ON expenses(authorityId,year,month,kind);
CREATE INDEX IF NOT EXISTS expense_supplier ON expenses(supplierKey,year,month);
CREATE INDEX IF NOT EXISTS expense_source ON expenses(sourceId);
CREATE INDEX IF NOT EXISTS expense_period ON expenses(kind,year,month);
CREATE INDEX IF NOT EXISTS authority_group ON authorities(role,sphere,uf,sourceId);
CREATE INDEX IF NOT EXISTS authority_source ON authorities(sourceId);
CREATE INDEX IF NOT EXISTS authority_name ON authorities(name,id);
CREATE INDEX IF NOT EXISTS expense_kind_date ON expenses(kind,year DESC,month DESC,date DESC,id);
CREATE INDEX IF NOT EXISTS expense_kind_amount ON expenses(kind,amountCents DESC,id);
CREATE TABLE IF NOT EXISTS authority_totals(authorityId TEXT,kind TEXT,amountCents INTEGER,count INTEGER,
 periodStart TEXT,periodEnd TEXT,monthCount INTEGER,PRIMARY KEY(authorityId,kind));
CREATE TABLE IF NOT EXISTS supplier_totals(supplierKey TEXT PRIMARY KEY,amountCents INTEGER,count INTEGER,authorityCount INTEGER);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS signals(id TEXT PRIMARY KEY,authorityId TEXT,sourceId TEXT,type TEXT,title TEXT,
 amountCents INTEGER,description TEXT,period TEXT,detail TEXT);
CREATE INDEX IF NOT EXISTS signals_authority ON signals(authorityId,type);
-- Quem está em cada lista oficial na coleta completa mais recente; o cadastro e o histórico ficam em authorities.
CREATE TABLE IF NOT EXISTS roster(sourceId TEXT NOT NULL REFERENCES sources(id),
 authorityId TEXT NOT NULL REFERENCES authorities(id), PRIMARY KEY(sourceId,authorityId));
CREATE INDEX IF NOT EXISTS roster_authority ON roster(authorityId);
-- v5: notas da cota de anos anteriores do mandato (Câmara e Senado, desde fev/2023), em formato enxuto.
-- A fonte é derivada da Casa e do ano (camara_ceap_<ano>, senado_ceaps_<ano>); a visão quota_history
-- remonta as colunas das notas detalhadas para as consultas tratarem os dois períodos do mesmo jeito.
CREATE TABLE IF NOT EXISTS quota_categories(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS quota_history_notes(authorityId TEXT NOT NULL REFERENCES authorities(id),
 year INTEGER NOT NULL, month INTEGER NOT NULL, seq INTEGER NOT NULL, date TEXT,
 categoryId INTEGER NOT NULL REFERENCES quota_categories(id), amountCents INTEGER NOT NULL,
 complement INTEGER NOT NULL DEFAULT 0, supplierKey TEXT REFERENCES suppliers(key), documentPath TEXT,
 PRIMARY KEY(authorityId,year,month,seq)) WITHOUT ROWID;
CREATE VIEW IF NOT EXISTS quota_history AS SELECT n.authorityId,
 CASE WHEN n.authorityId LIKE 'senado:%' THEN 'senado_ceaps_' ELSE 'camara_ceap_' END || n.year sourceId,
 n.year,n.month,n.seq,n.date,c.name category,
 CASE n.complement WHEN 1 THEN 'complemento_moradia' ELSE 'reembolso' END kind,
 n.amountCents,n.supplierKey,
 CASE WHEN n.documentPath IS NULL OR n.documentPath LIKE 'http%' THEN n.documentPath
  ELSE 'https://www.camara.leg.br/cota-parlamentar/' || n.documentPath END documentUrl
 FROM quota_history_notes n JOIN quota_categories c ON c.id=n.categoryId;
-- v6: alertas com o resultado gravado (signals.detail), cobertura por regra e período e o valor das
-- despesas nos alertas por pessoa, contando cada lançamento uma vez só (backend/alert_rules.py).
CREATE TABLE IF NOT EXISTS alert_coverage(authorityId TEXT NOT NULL, sourceId TEXT NOT NULL, year INTEGER NOT NULL,
 rule TEXT NOT NULL, detail TEXT NOT NULL, PRIMARY KEY(authorityId,sourceId,year,rule)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS alert_totals(authorityId TEXT PRIMARY KEY, amountCents INTEGER NOT NULL,
 records INTEGER NOT NULL, partial INTEGER NOT NULL DEFAULT 0);
