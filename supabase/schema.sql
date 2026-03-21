-- Childcare Directory — Supabase Schema
-- PostGIS required: enabled by default on Supabase

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------------------
-- institutions
-- ---------------------------------------------------------------------------
-- One row per institution from Carta Social, enriched with Google Places data.
-- The core differentiator of this directory is proximity search:
--
--   SELECT *, ST_Distance(location, ST_MakePoint(:lng, :lat)::geography) AS distance_m
--   FROM institutions
--   WHERE is_active = true
--     AND ST_DWithin(location, ST_MakePoint(:lng, :lat)::geography, :radius_m)
--   ORDER BY is_premium DESC, distance_m ASC
--   LIMIT 50;
--
-- Premium institutions surface first within the radius.
-- ---------------------------------------------------------------------------

CREATE TABLE institutions (
  -- Source data (Carta Social)
  id                    integer PRIMARY KEY,
  nome                  text NOT NULL,
  nome_google           text,
  morada                text,
  codigo_postal         varchar(8),
  localidade            text,
  freguesia             text,
  concelho              text,
  distrito              text,
  tipo                  text,             -- 'Creche' | 'Jardim de Infância'
  natureza_juridica     text,
  entidade_proprietaria text,
  capacidade            integer,
  utentes               integer,
  horario               text,
  telefone              text,
  telefone_google       text,
  email                 text,
  website_google        text,
  ultima_atualizacao    date,

  -- Geography
  location              geography(Point, 4326),

  -- Directory management
  is_premium            boolean     DEFAULT false,  -- flip manually after payment
  is_active             boolean     DEFAULT true,   -- false = closed/defunct
  created_at            timestamptz DEFAULT now(),
  updated_at            timestamptz DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

-- Proximity search (the core query)
CREATE INDEX idx_institutions_location ON institutions USING GIST (location);

-- Filtering
CREATE INDEX idx_institutions_concelho ON institutions (concelho);
CREATE INDEX idx_institutions_distrito ON institutions (distrito);
CREATE INDEX idx_institutions_tipo     ON institutions (tipo);

-- Partial index — only premium rows (small, fast for ORDER BY is_premium DESC)
CREATE INDEX idx_institutions_premium ON institutions (is_premium) WHERE is_premium = true;

-- Full-text search on institution name
CREATE INDEX idx_institutions_nome_fts ON institutions
  USING GIN (to_tsvector('portuguese', nome));

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
-- Public read-only. No auth required.

ALTER TABLE institutions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public read"
  ON institutions FOR SELECT
  USING (true);
