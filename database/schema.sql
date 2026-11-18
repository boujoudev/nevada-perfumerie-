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
    note       TEXT,
    utilisateur_id INTEGER REFERENCES utilisateurs(id),   -- qui a vendu
    session_id INTEGER REFERENCES sessions_caisse(id)      -- dans quelle session de caisse
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
    details      TEXT,
    utilisateur_id INTEGER REFERENCES utilisateurs(id),
    session_id   INTEGER
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
    ('schema_version', '5');

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


-- ============================================================
--  MODULE COSMÉTIQUE (caisse) + UTILISATEURS + SESSIONS (version 5)
-- ============================================================

-- ----------------------- UTILISATEURS -----------------------
CREATE TABLE IF NOT EXISTS utilisateurs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nom               TEXT NOT NULL CHECK (length(trim(nom)) > 0),
    identifiant       TEXT NOT NULL,
    mot_de_passe_hash TEXT NOT NULL,
    mot_de_passe_sel  TEXT NOT NULL,
    role              TEXT NOT NULL DEFAULT 'CAISSIER' CHECK (role IN ('ADMIN', 'CAISSIER')),
    actif             INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    date_creation     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_utilisateurs_identifiant ON utilisateurs(identifiant COLLATE NOCASE);

-- ------------------- SESSIONS DE CAISSE ---------------------
-- Un seul tiroir-caisse : UNE session ouverte à la fois (les ventes vont dans celle-là).
-- Une session peut être mise EN_PAUSE (sans être clôturée) quand un autre employé prend la caisse.
CREATE TABLE IF NOT EXISTS sessions_caisse (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    utilisateur_id    INTEGER NOT NULL REFERENCES utilisateurs(id),
    date_ouverture    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    fond_ouverture    REAL NOT NULL DEFAULT 0 CHECK (fond_ouverture >= 0),
    ecart_passation   REAL NOT NULL DEFAULT 0,
    statut            TEXT NOT NULL DEFAULT 'OUVERTE' CHECK (statut IN ('OUVERTE', 'EN_PAUSE', 'CLOTUREE')),
    date_cloture      TEXT,
    -- chiffres figés à la clôture (une session clôturée ne change plus)
    total_ventes_cosmetique REAL, total_ventes_parfum REAL, total_retours REAL,
    entrees_caisse    REAL, sorties_caisse REAL,
    especes_attendues REAL, especes_comptees REAL,
    ecart             REAL,
    note              TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_une_session_ouverte ON sessions_caisse(statut) WHERE statut = 'OUVERTE';
CREATE INDEX IF NOT EXISTS idx_sessions_utilisateur ON sessions_caisse(utilisateur_id);

CREATE TABLE IF NOT EXISTS mouvements_caisse (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES sessions_caisse(id),
    utilisateur_id INTEGER NOT NULL REFERENCES utilisateurs(id),
    date_mouvement TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    type           TEXT NOT NULL CHECK (type IN ('ENTREE', 'SORTIE')),
    montant        REAL NOT NULL CHECK (montant > 0),
    motif          TEXT NOT NULL CHECK (length(trim(motif)) > 0)
);
CREATE INDEX IF NOT EXISTS idx_mouvements_session ON mouvements_caisse(session_id);

-- ---------------------- PRODUITS CAISSE ---------------------
CREATE TABLE IF NOT EXISTS produits_caisse (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    code           TEXT,
    nom            TEXT NOT NULL CHECK (length(trim(nom)) > 0),
    categorie      TEXT,
    prix_achat     REAL NOT NULL DEFAULT 0 CHECK (prix_achat >= 0),
    prix_vente     REAL NOT NULL DEFAULT 0 CHECK (prix_vente >= 0),
    quantite_stock INTEGER NOT NULL DEFAULT 0,
    seuil_alerte   INTEGER NOT NULL DEFAULT 5,
    actif          INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1)),
    date_creation  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_produits_caisse_code ON produits_caisse(code COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_produits_caisse_nom ON produits_caisse(nom COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS codes_barres (
    code_barre TEXT PRIMARY KEY,
    produit_id INTEGER NOT NULL REFERENCES produits_caisse(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_codes_barres_produit ON codes_barres(produit_id);

-- --------------------------- TICKETS ------------------------
CREATE TABLE IF NOT EXISTS tickets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES sessions_caisse(id),
    utilisateur_id INTEGER NOT NULL REFERENCES utilisateurs(id),
    client_id      INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    date_ticket    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    sous_total     REAL NOT NULL DEFAULT 0,       -- avant toute remise
    remise_totale  REAL NOT NULL DEFAULT 0,       -- remises de lignes + remise globale
    total          REAL NOT NULL DEFAULT 0,
    cout_total     REAL NOT NULL DEFAULT 0,
    benefice       REAL NOT NULL DEFAULT 0,
    montant_donne  REAL,
    monnaie_rendue REAL,
    statut         TEXT NOT NULL DEFAULT 'VALIDE' CHECK (statut IN ('VALIDE', 'ANNULE')),
    note           TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickets_date    ON tickets(date_ticket);
CREATE INDEX IF NOT EXISTS idx_tickets_session ON tickets(session_id);

CREATE TABLE IF NOT EXISTS lignes_ticket (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id          INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    produit_id         INTEGER NOT NULL REFERENCES produits_caisse(id),
    code_barre         TEXT,
    designation        TEXT NOT NULL,
    quantite           INTEGER NOT NULL CHECK (quantite > 0),
    prix_unitaire      REAL NOT NULL,
    remise_ligne       REAL NOT NULL DEFAULT 0,   -- remise de la ligne, part de la remise globale comprise
    total_ligne        REAL NOT NULL,             -- quantite x prix_unitaire - remise_ligne
    cout_unitaire      REAL NOT NULL,
    quantite_retournee INTEGER NOT NULL DEFAULT 0 CHECK (quantite_retournee >= 0 AND quantite_retournee <= quantite)
);
CREATE INDEX IF NOT EXISTS idx_lignes_ticket_ticket  ON lignes_ticket(ticket_id);
CREATE INDEX IF NOT EXISTS idx_lignes_ticket_produit ON lignes_ticket(produit_id);

CREATE TABLE IF NOT EXISTS tickets_en_attente (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    utilisateur_id INTEGER NOT NULL REFERENCES utilisateurs(id),
    date_creation  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    libelle        TEXT,
    contenu        TEXT NOT NULL
);

-- --------------------------- RETOURS ------------------------
CREATE TABLE IF NOT EXISTS retours (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions_caisse(id),
    utilisateur_id  INTEGER NOT NULL REFERENCES utilisateurs(id),
    ticket_id       INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    date_retour     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    total_rembourse REAL NOT NULL DEFAULT 0,
    motif           TEXT
);
CREATE INDEX IF NOT EXISTS idx_retours_date ON retours(date_retour);
CREATE INDEX IF NOT EXISTS idx_retours_session ON retours(session_id);

CREATE TABLE IF NOT EXISTS lignes_retour (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    retour_id               INTEGER NOT NULL REFERENCES retours(id) ON DELETE CASCADE,
    produit_id              INTEGER NOT NULL REFERENCES produits_caisse(id),
    ligne_ticket_id         INTEGER REFERENCES lignes_ticket(id) ON DELETE SET NULL,
    designation             TEXT NOT NULL,
    quantite                INTEGER NOT NULL CHECK (quantite > 0),
    prix_rembourse_unitaire REAL NOT NULL,
    cout_unitaire           REAL NOT NULL,
    remis_en_stock          INTEGER NOT NULL DEFAULT 1 CHECK (remis_en_stock IN (0, 1))
);

-- ---------------------- JOURNAL DE LA CAISSE ----------------
CREATE TABLE IF NOT EXISTS logs_caisse (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    date_log       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    type           TEXT NOT NULL CHECK (type IN ('VENTE', 'RETOUR', 'ACHAT', 'AJUSTEMENT', 'ANNULATION',
                       'CREATION', 'MODIFICATION', 'SUPPRESSION', 'IMPORT', 'OUVERTURE', 'PAUSE',
                       'REPRISE', 'CLOTURE', 'MOUVEMENT_CAISSE', 'CONNEXION')),
    utilisateur_id INTEGER REFERENCES utilisateurs(id),
    session_id     INTEGER,
    produit_id     INTEGER,
    produit_nom    TEXT,
    quantite       REAL,
    prix           REAL,
    benefice       REAL,
    ticket_id      INTEGER,
    details        TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_caisse_date ON logs_caisse(date_log);
CREATE INDEX IF NOT EXISTS idx_logs_caisse_type ON logs_caisse(type);
