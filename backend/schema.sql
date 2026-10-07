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
 periodStart TEXT,periodEnd TEXT,PRIMARY KEY(authorityId,kind));
CREATE TABLE IF NOT EXISTS supplier_totals(supplierKey TEXT PRIMARY KEY,amountCents INTEGER,count INTEGER,authorityCount INTEGER);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS signals(id TEXT PRIMARY KEY,authorityId TEXT,sourceId TEXT,type TEXT,title TEXT,
 amountCents INTEGER,description TEXT,period TEXT);
CREATE INDEX IF NOT EXISTS signals_authority ON signals(authorityId,type);
-- Quem está em cada lista oficial na coleta completa mais recente; o cadastro e o histórico ficam em authorities.
CREATE TABLE IF NOT EXISTS roster(sourceId TEXT NOT NULL REFERENCES sources(id),
 authorityId TEXT NOT NULL REFERENCES authorities(id), PRIMARY KEY(sourceId,authorityId));
CREATE INDEX IF NOT EXISTS roster_authority ON roster(authorityId);
