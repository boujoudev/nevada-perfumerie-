# Nevada — Gestion (Parfum + Cosmétique)

Application de bureau 100 % locale pour la boutique : **deux logiciels en un**.

- **PARFUM** : création des flacons / parfums / alcool, stock, vente de parfums composés, logs et statistiques.
- **COSMÉTIQUE** : une vraie **caisse** (codes-barres, panier, remises, retours, stock, clôture de caisse).

Technos : Python 3.11+, CustomTkinter, SQLite, Pillow, openpyxl (import Excel).

---

## 1. Lancer le programme (développement)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```
Sous Windows, `lancer.bat` fait tout. Tests : `python -m unittest discover -s tests -v`

## 2. Premier lancement : le compte administrateur

Au tout premier lancement, l'application demande de **créer le compte administrateur** (nom, identifiant,
mot de passe de 4 caractères minimum). Ensuite, l'administrateur ajoute les employés depuis la page d'accueil
(bouton **Utilisateurs**).
Si une ancienne version avait un mot de passe unique, il devient celui de l'utilisateur « admin ».

## 3. Page d'accueil et utilisateurs

Après la connexion : deux gros boutons **PARFUM** et **COSMÉTIQUE**. Dans chaque module, le bouton
**« ⬅ Retour à l'accueil »** (en bas du menu) revient à cette page. Autres boutons : sessions de caisse,
utilisateurs (admin), mon mot de passe, changer d'utilisateur, quitter.

| | Administrateur | Caissier |
|---|---|---|
| Parfum | tout (création, stock, vente, logs, paramètres) | **Vente** + Session seulement |
| Cosmétique | caisse, retours, stock complet, import, inventaire, logs et statistiques | caisse, retours, **consultation** du stock (sans prix d'achat) |
| Prix d'achat et bénéfices | visibles | cachés |
| Annuler un ticket / supprimer une vente | oui (session non clôturée) | non |
| Utilisateurs, statistiques, export | oui | non |

## 4. Sessions de caisse et clôture

Une **session = un employé + le tiroir-caisse**. Les ventes cosmétique **et** parfum sont comptées dans la
**session ouverte** (il n'y en a qu'une à la fois).

1. L'employé **ouvre sa session** en comptant le fond de caisse (proposé : l'argent compté à la dernière clôture).
2. Quand un autre employé prend la caisse, il ouvre la sienne : celle du premier passe **EN PAUSE** (sans être
   clôturée, c'est facultatif). Chacun peut **reprendre** sa session ou la **clôturer** plus tard.
3. **Clôture à l'aveugle** : l'employé compte tout l'argent du tiroir, puis l'application affiche
   `espèces attendues = fond + ventes cosmétique + ventes parfum + entrées − remboursements − sorties`
   et l'**écart** (négatif = **manque**). Une session clôturée ne change plus jamais.
4. **Écart de passation** : si le fond compté à l'ouverture diffère de l'argent compté à la clôture précédente,
   la différence est notée à part (elle n'est mise sur le compte de personne).
5. **Mouvements de caisse** (retrait pour la banque, dépense, versement) avec motif obligatoire.
6. **Historique** : écart de chaque session et cumul par employé ; **rapport de session** et **rapport de la
   journée** (enregistrables en .txt).

## 5. Module Cosmétique (la caisse)

- **Scan** : le lecteur USB « tape » le code puis Entrée → l'article s'ajoute (même produit = quantité +1).
  `3*code` ajoute 3 articles. Un produit sans code-barres se trouve par **nom** (suggestions pendant la frappe)
  ou par **ID**.
- **Panier** : quantité (F2), remise de ligne en % ou DA (F3), prix modifié (F4), retirer (Suppr),
  remise sur tout le ticket, client facultatif, **mise en attente** (F8) et reprise (F9).
- **Paiement** : montant donné → **monnaie à rendre**, encaisser (F12). Espèces uniquement, pas de crédit.
- **Stock insuffisant** : avertissement rouge, la vente reste possible (stock négatif).
- **Retours** : sur un ticket (remboursement au **prix réellement payé**, quantités contrôlées) ou **libre**
  (scan du produit) ; chaque article est **remis en stock** ou compté en **perte** (abîmé).
- **Stock** : plusieurs codes-barres par produit, ID personnalisable (jamais en double), réception de
  marchandise (le prix d'achat devient le dernier prix saisi), **inventaire** (stock compté), import.
- **Logs & statistiques** : ventes nettes (retours déduits), dépense nette, bénéfice net, tickets, panier moyen,
  top produits par quantité et par bénéfice, valeur du stock, écarts de caisse par employé, export CSV.

### Importer un catalogue (CSV ou Excel)
Première ligne = titres des colonnes (ordre libre, accents et majuscules ignorés) :
`code-barres ; nom (ou désignation) ; catégorie ; prix d'achat ; prix de vente ; stock ; seuil ; ID`
Seuls **nom** et **prix de vente** sont obligatoires. Un produit dont le code-barres existe déjà est mis à jour
(nom, catégorie, prix) **sans toucher à son stock**. Les lignes en erreur sont listées, les autres sont importées.

## 6. Module Parfum
Création (alcool calculé automatiquement = capacité − parfum), stock, vente (le vendeur saisit le prix, le
bénéfice se calcule), logs avec le nom de l'employé. Une vente de parfum exige une session ouverte. L'ID de
chaque produit est personnalisable.

## 7. Où sont les données ?

`%APPDATA%\GestionParfumerie\` (Mac/Linux : `~/.local/share/GestionParfumerie/`)

| Élément | Rôle |
|---|---|
| `parfumerie.db` | la base de données (tout est là) |
| `sauvegardes\` | copies automatiques (démarrage, fermeture, toutes les 30 min, 10 conservées) |
| `application.log` | journal des erreurs |

Si la base est corrompue, elle est mise de côté et la dernière sauvegarde saine est restaurée.
Une base d'une ancienne version est **mise à niveau automatiquement** (rien n'est perdu).

## 8. Fabriquer l'application pour le client (.exe)

> À faire **sur un PC Windows**.

1. Installer **Python 3.11+ 64 bits** (cocher *Add python.exe to PATH* et *tcl/tk*) et **Git**.
2. `git clone <votre dépôt>` puis double-clic sur **`build_windows.bat`** (installe, teste, construit).
3. Résultat : `dist\GestionParfumerie\GestionParfumerie.exe`. Copier **tout le dossier** dans
   `C:\Nevada Gestion\` et créer un raccourci sur le Bureau.
4. *(Optionnel)* Installateur : ouvrir `installer.iss` avec **Inno Setup** → *Build > Compile* →
   `installer\Setup_GestionParfumerie.exe`.

**Mise à jour** : `git pull`, relancer `build_windows.bat`, remplacer le dossier de l'application. Les données
(`%APPDATA%`) ne sont jamais touchées. Windows peut afficher « SmartScreen » (application non signée) :
*Informations complémentaires → Exécuter quand même*.

## 9. Changer le logo
`python outils/preparer_logo.py mon_logo.jpg` régénère `assets/` (logo sans fond, icônes), puis reconstruire.

## 10. Architecture

```
main.py                    point d'entrée
models/                    catalogues des champs (produits parfum, produits caisse)
database/                  schema.sql, connexion, migrations, sauvegardes, récupération
repositories/              accès SQL
services/                  logique métier (testée) : utilisateurs, sessions, caisse, parfum, statistiques
views/                     écrans CustomTkinter (aucun SQL) : application, accueil, modules, caisse, retours...
utils/                     formats, mots de passe, contexte, ressources
assets/  outils/           logo et icônes, outil de préparation du logo
tests/                     tests unitaires + parcours complet des écrans
```

## 11. Dépannage

| Problème | Solution |
|---|---|
| `No module named tkinter` | Réinstaller Python en cochant *tcl/tk and IDLE* |
| Import Excel impossible | `pip install openpyxl` (ou enregistrer le fichier en CSV) |
| L'.exe ne démarre pas | Ouvrir `%APPDATA%\GestionParfumerie\application.log` |
| Mot de passe oublié | Fermer l'application puis lancer `python outils/reinitialiser_mot_de_passe.py` (les mots de passe sont chiffrés : on ne peut pas les relire, seulement en définir un nouveau ; une copie de la base est faite avant) |
| « Impossible d'écrire le fichier » à l'export | Fermer le CSV dans Excel puis réessayer |
