-- ============================================================
--  Gestion Parfumerie - Schéma SQLite (version 1)
--  Conventions :
--    * Toutes les quantités de liquide (parfum, alcool) sont en ml
--    * Prix du parfum pour 100 ml ; prix de l'alcool au LITRE
--    * Les colonnes prix_vente* des produits sont OBSOLÈTES (non utilisées) : le prix de
--      vente est saisi à chaque vente. Elles sont conservées pour la compatibilité.
--    * Les stocks peuvent devenir négatifs (vente autorisée en rupture)
--    * "actif" = suppression douce (l'historique reste intact)
--    * lignes_vente contient des "snapshots" : l'historique ne change
--      pas si les tarifs changent plus tard
-- ============================================================

PRAGMA foreign_keys = ON;

-- ------------------------- PRODUITS -------------------------

CREATE TABLE IF NOT EXISTS flacons (
    code                  TEXT,   -- ID choisi par l'utilisateur (unique, voir index créés au démarrage)
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    nom                   TEXT    NOT NULL CHECK (length(trim(nom)) > 0),
    capacite_ml           REAL    NOT NULL CHECK (capacite_ml > 0),
    prix_achat            REAL    NOT NULL DEFAULT 0 CHECK (prix_achat >= 0),
    prix_vente            REAL    NOT NULL DEFAULT 0 CHECK (prix_vente >= 0),
    quantite_stock        INTEGER NOT NULL DEFAULT 0,
    qnt_alcool_necessaire REAL    NOT NULL DEFAULT 0 CHECK (qnt_alcool_necessaire >= 0),
    qnt_parfum_necessaire REAL    NOT NULL DEFAULT 0 CHECK (qnt_parfum_necessaire >= 0),
    seuil_alerte          REAL    NOT NULL DEFAULT 5,
    actif                 INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    date_creation         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS parfums (
    code                  TEXT,   -- ID choisi par l'utilisateur (unique, voir index créés au démarrage)
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nom               TEXT    NOT NULL CHECK (length(trim(nom)) > 0),
    prix_achat_100ml  REAL    NOT NULL DEFAULT 0 CHECK (prix_achat_100ml >= 0),
    prix_vente_100ml  REAL    NOT NULL DEFAULT 0 CHECK (prix_vente_100ml >= 0),
    quantite_stock_ml REAL    NOT NULL DEFAULT 0,
    seuil_alerte      REAL    NOT NULL DEFAULT 100,
    actif             INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    date_creation     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS alcools (
    code                  TEXT,   -- ID choisi par l'utilisateur (unique, voir index créés au démarrage)
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nom               TEXT    NOT NULL CHECK (length(trim(nom)) > 0),
    prix_achat_litre  REAL    NOT NULL DEFAULT 0 CHECK (prix_achat_litre >= 0),
    prix_vente_litre  REAL    NOT NULL DEFAULT 0 CHECK (prix_vente_litre >= 0),
    quantite_stock_ml REAL    NOT NULL DEFAULT 0,
    seuil_alerte      REAL    NOT NULL DEFAULT 1000,
    actif             INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    date_creation     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ------------------------- CLIENTS --------------------------

CREATE TABLE IF NOT EXISTS clients (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nom           TEXT NOT NULL CHECK (length(trim(nom)) > 0),
    telephone     TEXT,
    note          TEXT,
    actif         INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    date_creation TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- -------------------------- VENTES --------------------------
-- Une vente peut contenir plusieurs combinaisons (lignes_vente).
-- Supprimer une vente = DELETE + remise du stock + log (fait par le service).

CREATE TABLE IF NOT EXISTS ventes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    date_vente TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    total      REAL NOT NULL DEFAULT 0,
    cout_total REAL NOT NULL DEFAULT 0,
    benefice   REAL NOT NULL DEFAULT 0,
    note       TEXT
);

CREATE TABLE IF NOT EXISTS lignes_vente (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    vente_id      INTEGER NOT NULL REFERENCES ventes(id) ON DELETE CASCADE,
    flacon_id     INTEGER NOT NULL REFERENCES flacons(id),
    parfum_id     INTEGER NOT NULL REFERENCES parfums(id),
    alcool_id     INTEGER REFERENCES alcools(id),

    -- 1 = le client apporte son propre flacon :
    --     prix_flacon = 0, cout_flacon = 0, stock flacon NON décrémenté.
    --     (flacon_id sert quand même de "recette" : quantités parfum/alcool)
    flacon_client INTEGER NOT NULL DEFAULT 0 CHECK (flacon_client IN (0, 1)),

    -- Snapshots (historique figé)
    flacon_nom    TEXT NOT NULL,
    parfum_nom    TEXT NOT NULL,
    qnt_parfum_ml REAL NOT NULL,
    qnt_alcool_ml REAL NOT NULL DEFAULT 0,
    prix_flacon   REAL NOT NULL DEFAULT 0,
    prix_parfum   REAL NOT NULL DEFAULT 0,
    prix_alcool   REAL NOT NULL DEFAULT 0,
    prix_calcule  REAL NOT NULL,   -- somme automatique
    prix_final    REAL NOT NULL,   -- après modification manuelle éventuelle
    cout_flacon   REAL NOT NULL DEFAULT 0,
    cout_parfum   REAL NOT NULL DEFAULT 0,
    cout_alcool   REAL NOT NULL DEFAULT 0,
    benefice      REAL NOT NULL    -- prix_final - (cout_flacon + cout_parfum + cout_alcool)
);

-- --------------------------- LOGS ---------------------------
-- Pas de clé étrangère vers ventes : le log survit à la suppression
-- d'une vente (le détail est conservé dans "details").

CREATE TABLE IF NOT EXISTS logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date_log     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    type         TEXT NOT NULL CHECK (type IN
                    ('VENTE', 'ACHAT', 'AJUSTEMENT', 'ANNULATION',
                     'CREATION', 'MODIFICATION', 'SUPPRESSION')),
    produit_type TEXT CHECK (produit_type IN ('FLACON', 'PARFUM', 'ALCOOL')),
    produit_id   INTEGER,
    produit_nom  TEXT,
    quantite     REAL,
    prix         REAL,
    benefice     REAL,
    vente_id     INTEGER,
    details      TEXT
);

-- ------------------------ PARAMÈTRES ------------------------

CREATE TABLE IF NOT EXISTS parametres (
    cle    TEXT PRIMARY KEY,
    valeur TEXT NOT NULL
);

INSERT OR IGNORE INTO parametres (cle, valeur) VALUES
    ('devise', 'DA'),
    ('mot_de_passe_hash', ''),
    ('mot_de_passe_sel', ''),
    ('schema_version', '4');

-- -------------------------- INDEX ---------------------------

CREATE INDEX IF NOT EXISTS idx_flacons_nom   ON flacons(nom COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_parfums_nom   ON parfums(nom COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_alcools_nom   ON alcools(nom COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_clients_nom   ON clients(nom COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_ventes_date   ON ventes(date_vente);
CREATE INDEX IF NOT EXISTS idx_ventes_client ON ventes(client_id);
CREATE INDEX IF NOT EXISTS idx_lignes_vente  ON lignes_vente(vente_id);
CREATE INDEX IF NOT EXISTS idx_lignes_flacon ON lignes_vente(flacon_id);
CREATE INDEX IF NOT EXISTS idx_lignes_parfum ON lignes_vente(parfum_id);
CREATE INDEX IF NOT EXISTS idx_logs_date     ON logs(date_log);
CREATE INDEX IF NOT EXISTS idx_logs_type     ON logs(type);
