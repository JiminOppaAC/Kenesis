# Kinesis

**FR** — Fonds d'écran animés (vidéo, GIF, image) pour Windows, pensé pour les écrans ultrawide et le multi-écrans. Simple, sans son, **100 % local** (aucune connexion à Internet).

**EN** — Animated wallpapers (video, GIF, image) for Windows, designed for ultrawide and multi-monitor setups. Simple, silent, **100% local** (no network access).

## Fonctionnalités / Features
- Vidéos (MP4, WebM, MKV, MOV, AVI), GIF animés et images / Videos, animated GIFs and images
- Un fond différent par écran, avec ajustement (remplir, ajuster, étirer) / A different wallpaper per screen, with fit modes
- Bibliothèque avec recherche et tri, glisser-déposer sur un écran / Library with search, sorting and drag & drop
- Pause automatique (appli en plein écran, bureau caché) / Auto-pause (fullscreen app, covered desktop)
- Arrêt propre à la veille et au verrouillage / Clean stop on sleep and lock
- Français et anglais / French and English

## Installation
1. Télécharge `Kinesis_Setup_x.y.z.exe` dans l'onglet **Releases** / Download it from the **Releases** tab.
2. Lance-le. Windows peut afficher « Windows a protégé votre ordinateur » (le programme n'est pas signé) : clique sur **Informations complémentaires** puis **Exécuter quand même**.
   *Windows may show a SmartScreen warning because the app is unsigned: click **More info**, then **Run anyway**.*

Windows 10 / 11 (64 bits). Développé et testé sur Windows 11 (24H2) ; les autres versions de Windows n'ont pas encore été testées.
*Developed and tested on Windows 11 (24H2); other Windows versions have not been tested yet.*

## Lancer depuis les sources / Run from source
```
py -3.13 -m pip install -r requirements.txt
py -3.13 kinesis.py
```
Créer l'installateur / Build the installer : lancer `build_exe.bat`, puis compiler `kinesis_installer.iss` avec [Inno Setup](https://jrsoftware.org/isinfo.php).

## Crédits et licences / Credits and licenses
- Interface : [PySide6 / Qt](https://www.qt.io/qt-for-python) (LGPL).
- Police / Font : [Arvo](https://fonts.google.com/specimen/Arvo) (SIL Open Font License, voir `assets/fonts/OFL.txt`).
- Le code de Kinesis est publié sous la licence indiquée dans le fichier `LICENSE`.
