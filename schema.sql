-- ============================================================
-- Creches.pt — Supabase schema
-- Run this once in the Supabase SQL editor
-- ============================================================

-- Enable PostGIS (should already be enabled on Supabase)
CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================================
-- 1. Main institutions table
-- ============================================================

CREATE TABLE IF NOT EXISTS instituicoes (
  id                TEXT PRIMARY KEY,          -- Carta Social ID
  slug              TEXT UNIQUE NOT NULL,       -- [id]-[nome-slugified]
  nome              TEXT NOT NULL,
  nome_google       TEXT,
  tipo              TEXT,                       -- 'Creche', 'Jardim de Infância', etc.
  natureza_juridica TEXT,                       -- 'IPSS', 'Privado', 'Público'
  morada            TEXT,
  codigo_postal     TEXT,
  localidade        TEXT,
  concelho          TEXT,
  distrito          TEXT,
  telefone          TEXT,
  telefone_google   TEXT,
  email             TEXT,
  website_google    TEXT,
  place_id          TEXT,                       -- Google Places ID (for on-demand photos)
  capacidade        INTEGER,
  utentes           INTEGER,
  horario           TEXT,
  ultima_atualizacao DATE,
  location          GEOGRAPHY(POINT, 4326),     -- PostGIS point
  search_vector     TSVECTOR                    -- full-text search
);

-- Spatial index for radius queries
CREATE INDEX IF NOT EXISTS idx_instituicoes_location
  ON instituicoes USING GIST(location);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_instituicoes_search
  ON instituicoes USING GIN(search_vector);

-- Index for postcode lookups
CREATE INDEX IF NOT EXISTS idx_instituicoes_cp
  ON instituicoes(codigo_postal);

-- Index for filtering by type
CREATE INDEX IF NOT EXISTS idx_instituicoes_natureza
  ON instituicoes(natureza_juridica);

-- Auto-update search_vector on insert/update
CREATE OR REPLACE FUNCTION update_search_vector()
RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('pg_catalog.portuguese', coalesce(NEW.nome, '')), 'A') ||
    setweight(to_tsvector('pg_catalog.portuguese', coalesce(NEW.localidade, '')), 'B') ||
    setweight(to_tsvector('pg_catalog.portuguese', coalesce(NEW.concelho, '')), 'B') ||
    setweight(to_tsvector('pg_catalog.portuguese', coalesce(NEW.distrito, '')), 'C');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tsvector_update
  BEFORE INSERT OR UPDATE ON instituicoes
  FOR EACH ROW EXECUTE FUNCTION update_search_vector();

-- RLS: all rows readable by anon (public directory)
ALTER TABLE instituicoes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public read" ON instituicoes FOR SELECT USING (true);

-- ============================================================
-- 2. PostGIS radius search RPC
-- ============================================================

CREATE OR REPLACE FUNCTION nearby_instituicoes(
  lat         FLOAT,
  lng         FLOAT,
  radius_m    INT,
  page_offset INT DEFAULT 0
)
RETURNS SETOF instituicoes AS $$
  SELECT * FROM instituicoes
  WHERE ST_DWithin(
    location,
    ST_MakePoint(lng, lat)::geography,
    LEAST(radius_m, 50000)   -- cap at 50km to prevent full-table scans
  )
  ORDER BY ST_Distance(location, ST_MakePoint(lng, lat)::geography)
  LIMIT 50 OFFSET page_offset;
$$ LANGUAGE sql STABLE SECURITY DEFINER;

-- ============================================================
-- 3. Postcode lookup table (for frontend postcode search)
-- ============================================================

CREATE TABLE IF NOT EXISTS codigos_postais (
  codigo_postal TEXT PRIMARY KEY,
  latitude      FLOAT NOT NULL,
  longitude     FLOAT NOT NULL
);

-- No RLS needed — read via service role during postcode search
-- (or enable anon read if you prefer client-side lookup)
ALTER TABLE codigos_postais ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public read" ON codigos_postais FOR SELECT USING (true);
