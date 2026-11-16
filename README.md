# Nevada Parfumerie — Gestion

Application de bureau (100 % locale) pour gérer une boutique de parfumerie artisanale :
création des produits, stock, ventes (flacon + parfum + alcool), journal et statistiques.

**Technos :** Python 3.11+, CustomTkinter, SQLite, Pillow (réservé pour de futures photos produits).

---

## 1. Lancer le programme (développement)

1. Installer **Python 3.11 ou plus récent (64 bits)** depuis https://www.python.org/downloads/
   (laisser cochées les options *tcl/tk* et *Add python.exe to PATH*).
2. Double-cliquer sur **`lancer.bat`** (la 1re fois, il installe les dépendances).

Ou en ligne de commande :

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Lancer les tests : `python -m unittest discover -s tests -v`

## 2. Où sont les données ?

`%APPDATA%\GestionParfumerie\` (ex. `C:\Users\Nom\AppData\Roaming\GestionParfumerie\`)

| Élément | Rôle |
|---|---|
| `parfumerie.db` | la base de données (tout est là) |
| `sauvegardes\` | copies automatiques (démarrage, fermeture, toutes les 30 min, 10 conservées) |
| `application.log` | journal des erreurs (à demander au client en cas de souci) |

**Sauvegarde externe :** copier régulièrement le dossier `sauvegardes` sur une clé USB / un cloud.
**Si la base est corrompue :** l'application la met de côté et restaure la dernière sauvegarde saine toute seule.

## 3. Utilisation en bref

- **Création** : flacon, parfum, alcool (stocks et quantités en **ml**, prix du parfum pour **100 ml**, prix de l'alcool au **litre**). Le produit entre directement en stock.
- **Stock** : recherche par nom/ID/type, double-clic = modifier, `+ Ajouter du stock` (crée un « Achat » dans les logs), rouge = stock sous le seuil.
- **Vente** : choisir flacon + parfum (+ alcool), **saisir le prix de vente** (Entrée = ajouter au panier) ; le coût et le bénéfice s'affichent, avec le **bénéfice du panier** en bas ; le **TOTAL est modifiable** ; case « le client apporte son flacon » (coût du flacon non compté, stock inchangé) ; panier multi-articles ; `VALIDER LA VENTE`. Stock en rupture = avertissement, vente quand même possible (stock négatif).
- **Logs & Stats** : historique filtrable, export CSV (Excel), CA / bénéfice jour-mois-année, top 5, valeur du stock. On peut **supprimer une vente** : stocks remis + trace dans les logs.
- **Paramètres** : mot de passe (facultatif), sauvegarde manuelle.

**Calculs :** il n'y a **pas de prix de vente** dans les fiches produits : le vendeur saisit le prix à chaque vente. Coût parfum = ml × prix d'achat (100 ml) / 100 · coût alcool = ml × prix d'achat (litre) / 1000 · **alcool par flacon = capacité − parfum (automatique)** · bénéfice = prix saisi − coût de revient.

## 4. Fabriquer l'application pour le client (.exe)

> ⚠ À faire **sur un PC Windows** (PyInstaller ne crée pas de .exe Windows depuis un autre système).

1. Double-cliquer sur **`build_windows.bat`** (il installe tout, lance les tests, puis construit).
2. Résultat : dossier **`dist\GestionParfumerie\`** contenant `GestionParfumerie.exe`.

### Option A — Installateur (recommandé)
1. Installer **Inno Setup** (gratuit) : https://jrsoftware.org/isdl.php
2. Ouvrir `installer.iss` → *Build > Compile*.
3. Donner **`installer\Setup_GestionParfumerie.exe`** au client : il double-clique, suit l'assistant, et a un raccourci Bureau + menu Démarrer. Pas besoin de droits administrateur.

### Option B — Copie simple
1. Copier tout le dossier `dist\GestionParfumerie` sur le PC du client (ex. `C:\GestionParfumerie`).
2. Clic droit sur `GestionParfumerie.exe` → *Envoyer vers* → *Bureau (créer un raccourci)*.

Le client n'a **pas besoin d'installer Python**.

### Avant de livrer
- Tester l'installateur sur un autre PC (ou une machine virtuelle) **propre**.
- Windows peut afficher « SmartScreen a protégé votre ordinateur » (application non signée) : *Informations complémentaires → Exécuter quand même*. Un certificat de signature de code (payant) supprime ce message.
- Certains antivirus signalent à tort les .exe PyInstaller : c'est pourquoi le mode « dossier » (et non « un seul fichier ») est utilisé.

## 5. Mises à jour et changement de PC

- **Mise à jour :** reconstruire, puis réinstaller par-dessus (ou remplacer le dossier de l'application). Les données du client (`%APPDATA%`) ne sont jamais touchées.
- **Nouveau PC :** installer l'application, puis copier `parfumerie.db` dans `%APPDATA%\GestionParfumerie\` (application fermée).
- **Mot de passe oublié :** il ne peut pas être récupéré depuis l'application ; il faut intervenir sur la base (table `parametres`, vider `mot_de_passe_hash` et `mot_de_passe_sel`).

## 6. Architecture

```
main.py                    point d'entrée
assets/                    logo Nevada et icônes (logo.png, icone.ico, icone.png, icone.icns)
outils/preparer_logo.py    régénère les images à partir du logo d'origine
models/catalogue.py        description des 3 types de produits et de leurs champs
database/                  schema.sql, connexion, sauvegardes, récupération
repositories/              accès SQL uniquement
services/                  logique métier (prix, stock, ventes, stats, auth) — testée
views/                     écrans CustomTkinter (aucun SQL)
utils/                     formats, validation, mot de passe
tests/                     tests unitaires + test de fumée des écrans
```
Les vues appellent les services ; les services appellent les repositories. Chaque vente est une transaction unique (tout passe ou rien).

## 7. Changer le logo

Remplacer par un autre fichier image, puis lancer (Pillow installé) :
`python outils/preparer_logo.py mon_logo.jpg`
Cela régénère tout le dossier `assets/` (logo sans fond, icônes). Reconstruire ensuite l'application (`build_windows.bat`).

## 8. Dépannage

| Problème | Solution |
|---|---|
| `No module named tkinter` | Réinstaller Python en cochant *tcl/tk and IDLE* |
| L'.exe ne démarre pas | Ouvrir `%APPDATA%\GestionParfumerie\application.log` |
| « Impossible d'écrire le fichier » à l'export | Fermer le CSV dans Excel puis réessayer |
