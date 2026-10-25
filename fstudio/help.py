"""Aide intégrée (F1)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QListWidget, QPushButton, QTextBrowser, QVBoxLayout)

from . import i18n

SHORTCUTS = [
    ("F1", "Aide", "Help"),
    ("Ctrl+O", "Ouvrir une image dans l'explorateur", "Open an image in the explorer"),
    ("Ctrl+R", "Lire la disquette", "Read the disk"),
    ("Ctrl+Shift+W", "Écrire l'image choisie sur la disquette", "Write the selected image to disk"),
    ("Échap", "Annuler l'opération en cours", "Cancel the running operation"),
    ("Ctrl+F", "Rechercher (explorateur ou catalogue)", "Search (explorer or catalogue)"),
    ("Ctrl+E", "Exporter la sélection de l'explorateur", "Export the explorer selection"),
    ("Ctrl+1 … Ctrl+0", "Aller aux pages Lire … Appareil", "Go to pages Read … Device"),
    ("F5", "Rafraîchir les ports série", "Refresh serial ports"),
    ("Ctrl+,", "Préférences", "Preferences"),
    ("Ctrl+Q", "Quitter", "Quit"),
]

FR = {
    "Démarrage rapide": """
<h2>Démarrage rapide</h2>
<ol>
<li>Branchez le Greaseweazle en USB : Windows l'installe comme port série (aucun pilote à ajouter).</li>
<li>Le port est détecté et connecté automatiquement ; sinon choisissez-le en haut et cliquez <b>Connecter</b>.</li>
<li>Choisissez le lecteur : <b>A</b> pour un lecteur PC branché après la torsade du câble.</li>
<li>Insérez une disquette, choisissez le <b>Format actif</b> dans la barre du haut (ou cliquez <b>🔍 Détecter</b>) : il s'applique à toutes les pages.</li>
<li>Page <b>Lire</b> : cliquez <b>Lire la disquette</b>. La carte montre chaque
piste en direct (vert : OK, orange : relue, rouge : illisible).</li>
<li>Cliquez <b>Explorer l'image lue</b> pour parcourir les fichiers.</li>
</ol>
<p>Sans lecteur, l'explorateur, le catalogue, la conversion et l'analyse d'images flux fonctionnent sur des
fichiers image.</p>""",
    "Câblage et lecteurs": """
<h2>Câblage et choix du lecteur</h2>
<ul>
<li><b>Câble PC avec torsade</b> (fils 10–16 croisés) : le lecteur branché <i>après</i> la torsade est
<b>A</b>, celui du milieu est <b>B</b>.</li>
<li><b>Câble droit</b> : un lecteur 3,5" PC répond en général à <b>Shugart DS1</b> (cavalier DS1) ; les
lecteurs Amiga, Atari ou anciens 5,25" peuvent être en DS0.</li>
<li>Alimentez le lecteur par son propre connecteur (Molex ou Berg) : l'USB ne suffit pas.</li>
<li>Un lecteur 3,5" HD lit les disquettes DD et HD. Pour <b>écrire</b> une disquette DD dans un lecteur HD,
masquez le trou HD ou utilisez une vraie disquette DD.</li>
<li>Pour les formats 40 pistes (CPC, Thomson 5,25", PC 360 Ko) sur un lecteur 80 pistes, Floppy Studio
écrit les 40 premières pistes ; les lecteurs 40 pistes d'origine relisent ces disquettes s'ils ont été
écrits sur disquette vierge (effacée).</li>
<li>Le firmware se met à jour depuis la page <b>Outils</b>.</li>
</ul>""",
    "Formats par machine": """
<h2>Formats par machine</h2>
<table border=1 cellpadding=4 cellspacing=0>
<tr><th>Machine</th><th>Lecture</th><th>Image</th><th>Explorateur</th></tr>
<tr><td>PC / DOS</td><td>ibm.360 … ibm.2880</td><td>.img</td><td>FAT12/16, noms longs</td></tr>
<tr><td>Atari ST</td><td>atarist.720…</td><td>.st / .msa</td><td>FAT (TOS)</td></tr>
<tr><td>Amiga</td><td>amiga.amigados</td><td>.adf</td><td>OFS / FFS</td></tr>
<tr><td>Commodore</td><td>commodore.1541 / 1581</td><td>.d64 / .d81</td><td>CBM DOS</td></tr>
<tr><td>Amstrad CPC</td><td>Auto (scan) 40 pistes</td><td>.dsk (EDSK)</td><td>AMSDOS Data / Système / IBM</td></tr>
<tr><td>Thomson TO/MO</td><td>thomson.1s320 / 2s320</td><td>.fd</td><td>DOS BASIC</td></tr>
<tr><td>MSX</td><td>msx.2dd</td><td>.dsk</td><td>MSX-DOS (FAT)</td></tr>
<tr><td>Apple II</td><td>apple2 (lecteur 5,25" requis)</td><td>.dsk / .do / .po</td><td>DOS 3.3 / ProDOS</td></tr>
<tr><td>Sampleurs</td><td>akai.*, ensoniq.*, ibm.720</td><td>.img</td><td>Akai S900/S1000, DOS</td></tr>
<tr><td>Protégé / inconnu</td><td>Flux brut</td><td>.scp / .hfe</td><td>—</td></tr>
</table>
<p>Ouverture également : IMD, TD0 (Teledisk), DMK, 2MG, HFE, SCP, KryoFlux.</p>""",
    "Lecture et récupération": """
<h2>Lecture et récupération</h2>
<ul>
<li><b>Relectures</b> : nombre d'essais par piste ; <b>Repositionnements</b> : retour en piste 0 entre les
séries d'essais (utile sur les lecteurs fatigués).</li>
<li><b>Garder aussi le flux brut</b> : enregistre un .scp à côté de l'image. Le bouton
<b>Re-décoder le flux</b> recrée plus tard une image dans un autre format sans la disquette.</li>
<li><b>Profils</b> : enregistrez format, relectures, pistes et dossier (💾), rappelez-les d'un clic.</li>
<li><b>Lecture par lot</b> : enchaîne les disquettes, l'insertion de la suivante est détectée.</li>
<li>Page <b>Copier</b> : <b>Relire les secteurs illisibles</b> d'une image existante (multi-passes) ou
<b>fusionner</b> plusieurs lectures (lecteurs différents) ; <b>Comparer deux images</b> piste par piste.</li>
</ul>""",
    "Écriture et formatage": """
<h2>Écriture et formatage</h2>
<ul>
<li>Page <b>Écrire</b> : le format est deviné par l'extension ou la taille ; les flux (SCP, HFE) sont écrits
tels quels pour les disquettes protégées.</li>
<li>Page <b>Formater</b> : système de fichiers vierge (PC, Atari, MSX, Amiga, Thomson, CPC, C64 1581) ou
formatage bas niveau de n'importe quel format. <b>Créer une image vierge</b> la prépare pour un émulateur
ou pour y copier des fichiers dans l'explorateur avant écriture.</li>
<li>Vérifiez que l'onglet de protection est fermé (3,5" : fenêtre fermée).</li>
</ul>""",
    "Explorateur": """
<h2>Explorateur</h2>
<ul>
<li>Aperçus : texte (jeu de caractères au choix), BASIC (Locomotive, Thomson, MSX, GW, C64, Applesoft),
images (IFF, PCX, Degas, NEO, écran CPC, Koala), sons, hexadécimal, désassembleur.</li>
<li><b>Ajouter / Supprimer</b> des fichiers : FAT, CPC, Amiga, Thomson, Commodore 1541/1581 ; puis
<b>Enregistrer l'image</b> ou <b>Écrire sur la disquette</b>.</li>
<li><b>Occupation</b> : carte des blocs ; <b>Secteurs</b> : éditeur hexadécimal ; <b>Rechercher</b> : texte ou
octets dans toute l'image.</li>
<li>Les fichiers supprimés encore présents apparaissent dans « Fichiers supprimés ».</li>
<li><b>Exécuter</b> / <b>Lancer l'image</b> utilisent les émulateurs configurés (⚙).</li>
<li>Glissez des fichiers depuis l'Explorateur Windows sur l'arborescence pour les ajouter, ou depuis
l'arborescence vers Windows pour les extraire.</li>
</ul>""",
    "Qualité et protections": """
<h2>Qualité du signal et protections</h2>
<p>La <b>qualité</b> est la part des intervalles de flux proches des valeurs attendues : &gt; 97 %
excellent, 92–97 % correct, &lt; 90 % support ou alignement à vérifier. Le bouton <b>Santé</b> colore la
carte selon cette mesure.</p>
<p>L'<b>analyse approfondie</b> décode chaque tour séparément (secteurs faibles), recherche les secteurs
non standard et les pistes longues. Le rapport (📋) s'exporte en HTML ou PDF.</p>
<p>Page <b>Outils › Calibrage</b> : lecture en boucle de pistes de référence pour régler l'alignement.</p>""",
    "Catalogue": """
<h2>Catalogue</h2>
<p>Chaque image lue ou ouverte est ajoutée au catalogue (option). Recherchez par titre, étiquette, note ou
<b>nom de fichier contenu dans les images</b> ; double-cliquez pour ouvrir. Le bouton <b>Doublons</b> liste
les images identiques et les fichiers présents sur plusieurs disquettes. Export CSV.</p>""",
    "Raccourcis clavier": "",
    "Dépannage": """
<h2>Dépannage</h2>
<ul>
<li><b>Aucun port</b> : vérifiez le câble USB (certains ne transportent que l'alimentation).</li>
<li><b>Track 0 not found</b> : mauvais lecteur sélectionné (A/B/DS0/DS1) ou lecteur non alimenté.</li>
<li><b>No Index</b> : pas de disquette, moteur bloqué ou courroie usée.</li>
<li><b>Tout illisible</b> : mauvais format, tête sale (page Outils › Nettoyage) ou disquette démagnétisée.
Essayez la capture <b>flux brut</b> puis l'analyse d'image flux.</li>
<li><b>Vitesse hors tolérance</b> : 300 tr/min ±1,5 % attendus (Outils › Vitesse).</li>
</ul>""",
}

EN = {
    "Démarrage rapide": """
<h2>Quick start</h2>
<ol>
<li>Plug the Greaseweazle into USB: Windows installs it as a serial port (no driver needed).</li>
<li>The port is detected and connected automatically; otherwise pick it at the top and click <b>Connect</b>.</li>
<li>Choose the drive: <b>A</b> for a PC drive connected after the cable twist.</li>
<li>Insert a disk and pick the <b>Active format</b> in the top bar (or click <b>🔍 Detect</b>): it applies to every page.</li>
<li><b>Read</b> page: click <b>Read disk</b>. The map shows each track live
(green: OK, orange: re-read, red: unreadable).</li>
<li>Click <b>Explore read image</b> to browse the files.</li>
</ol>
<p>Without a drive, the explorer, catalogue, conversion and flux image analysis work on image files.</p>""",
    "Câblage et lecteurs": """
<h2>Cabling and drive selection</h2>
<ul>
<li><b>PC cable with twist</b> (wires 10–16 crossed): the drive <i>after</i> the twist is <b>A</b>, the middle
one is <b>B</b>.</li>
<li><b>Straight cable</b>: a 3.5" PC drive usually answers as <b>Shugart DS1</b>; Amiga, Atari or old 5.25"
drives may be DS0.</li>
<li>Power the drive from its own connector (Molex or Berg): USB is not enough.</li>
<li>A 3.5" HD drive reads DD and HD disks. To <b>write</b> a DD disk in an HD drive, cover the HD hole or use a
real DD disk.</li>
<li>40-track formats (CPC, Thomson 5.25", PC 360 KB) on an 80-track drive: the first 40 tracks are written;
original 40-track drives read them back best when written on a blank (erased) disk.</li>
<li>Firmware updates are in the <b>Tools</b> page.</li>
</ul>""",
    "Formats par machine": """
<h2>Formats by machine</h2>
<table border=1 cellpadding=4 cellspacing=0>
<tr><th>Machine</th><th>Read format</th><th>Image</th><th>Explorer</th></tr>
<tr><td>PC / DOS</td><td>ibm.360 … ibm.2880</td><td>.img</td><td>FAT12/16, long names</td></tr>
<tr><td>Atari ST</td><td>atarist.720…</td><td>.st / .msa</td><td>FAT (TOS)</td></tr>
<tr><td>Amiga</td><td>amiga.amigados</td><td>.adf</td><td>OFS / FFS</td></tr>
<tr><td>Commodore</td><td>commodore.1541 / 1581</td><td>.d64 / .d81</td><td>CBM DOS</td></tr>
<tr><td>Amstrad CPC</td><td>Auto (scan) 40 tracks</td><td>.dsk (EDSK)</td><td>AMSDOS Data / System / IBM</td></tr>
<tr><td>Thomson TO/MO</td><td>thomson.1s320 / 2s320</td><td>.fd</td><td>DOS BASIC</td></tr>
<tr><td>MSX</td><td>msx.2dd</td><td>.dsk</td><td>MSX-DOS (FAT)</td></tr>
<tr><td>Apple II</td><td>apple2 (5.25" drive needed)</td><td>.dsk / .do / .po</td><td>DOS 3.3 / ProDOS</td></tr>
<tr><td>Samplers</td><td>akai.*, ensoniq.*, ibm.720</td><td>.img</td><td>Akai S900/S1000, DOS</td></tr>
<tr><td>Protected / unknown</td><td>Raw flux</td><td>.scp / .hfe</td><td>—</td></tr>
</table>
<p>Also opens: IMD, TD0 (Teledisk), DMK, 2MG, HFE, SCP, KryoFlux.</p>""",
    "Lecture et récupération": """
<h2>Reading and recovery</h2>
<ul>
<li><b>Retries</b>: attempts per track; <b>Re-seeks</b>: return to track 0 between retry series (helps tired
drives).</li>
<li><b>Also keep the raw flux</b> saves a .scp next to the image. <b>Re-decode saved flux</b> later rebuilds an
image in another format without the disk.</li>
<li><b>Profiles</b>: save format, retries, tracks and folder (💾) and recall them in one click.</li>
<li><b>Batch reading</b>: reads disks in a row, the next insertion is detected.</li>
<li><b>Copy</b> page: <b>re-read unreadable sectors</b> of an existing image (multi-pass) or <b>merge</b> several
reads (different drives); <b>compare two images</b> track by track.</li>
</ul>""",
    "Écriture et formatage": """
<h2>Writing and formatting</h2>
<ul>
<li><b>Write</b> page: the format is guessed from the extension or size; flux images (SCP, HFE) are written
as-is for protected disks.</li>
<li><b>Format</b> page: blank file system (PC, Atari, MSX, Amiga, Thomson, CPC, C64 1581) or low-level format of
any format. <b>Create blank image</b> prepares it for an emulator or to copy files in the explorer before
writing.</li>
<li>Make sure the write-protect tab is closed.</li>
</ul>""",
    "Explorateur": """
<h2>Explorer</h2>
<ul>
<li>Previews: text (selectable charset), BASIC (Locomotive, Thomson, MSX, GW, C64, Applesoft), pictures (IFF,
PCX, Degas, NEO, CPC screen, Koala), sounds, hex, disassembler.</li>
<li><b>Add / Delete</b> files: FAT, CPC, Amiga, Thomson, Commodore 1541/1581; then <b>Save image</b> or
<b>Write to disk</b>.</li>
<li><b>Usage</b>: block map; <b>Sectors</b>: hex editor; <b>Search</b>: text or bytes in the whole image.</li>
<li>Deleted files still present are listed under "Deleted files".</li>
<li><b>Run</b> / <b>Boot image</b> use the configured emulators (⚙).</li>
<li>Drag files from Windows Explorer onto the tree to add them, or from the tree to Windows to extract.</li>
</ul>""",
    "Qualité et protections": """
<h2>Signal quality and protections</h2>
<p><b>Quality</b> is the share of flux intervals close to the expected values: &gt; 97 % excellent,
92–97 % fair, &lt; 90 % check media or alignment. The <b>Health</b> button colours the map with it.</p>
<p><b>Deep analysis</b> decodes each revolution separately (weak sectors), looks for non-standard sectors and
long tracks. The report (📋) exports to HTML or PDF.</p>
<p><b>Tools › Calibration</b>: reads reference tracks in a loop to adjust alignment.</p>""",
    "Catalogue": """
<h2>Catalogue</h2>
<p>Every read or opened image is added to the catalogue (optional). Search by title, label, note or <b>name of a
file inside the images</b>; double-click to open. <b>Duplicates</b> lists identical images and files present on
several disks. CSV export.</p>""",
    "Raccourcis clavier": "",
    "Dépannage": """
<h2>Troubleshooting</h2>
<ul>
<li><b>No port</b>: check the USB cable (some only carry power).</li>
<li><b>Track 0 not found</b>: wrong drive selected (A/B/DS0/DS1) or drive not powered.</li>
<li><b>No Index</b>: no disk, stuck motor or worn belt.</li>
<li><b>Everything unreadable</b>: wrong format, dirty head (Tools › Cleaning) or demagnetised disk. Try a
<b>raw flux</b> capture then flux image analysis.</li>
<li><b>Speed out of tolerance</b>: 300 rpm ±1.5 % expected (Tools › Speed).</li>
</ul>""",
}
TOPICS_EN = {"Démarrage rapide": "Quick start", "Câblage et lecteurs": "Cabling and drives",
             "Formats par machine": "Formats by machine", "Lecture et récupération": "Reading and recovery",
             "Écriture et formatage": "Writing and formatting", "Explorateur": "Explorer",
             "Qualité et protections": "Quality and protections", "Catalogue": "Catalogue",
             "Raccourcis clavier": "Keyboard shortcuts", "Dépannage": "Troubleshooting"}


def shortcuts_html(en: bool) -> str:
    rows = "".join(f"<tr><td><b>{k}</b></td><td>{e if en else f}</td></tr>" for k, f, e in SHORTCUTS)
    title = "Keyboard shortcuts" if en else "Raccourcis clavier"
    extra = ("<p>Drop several images or a folder on the window to add them to the catalogue or convert them "
             "in batch.</p>" if en else
             "<p>Déposez plusieurs images ou un dossier sur la fenêtre pour les ajouter au catalogue ou les "
             "convertir par lot.</p>")
    return f"<h2>{title}</h2><table cellpadding=5>{rows}</table>{extra}"


class HelpDialog(QDialog):
    def __init__(self, parent=None, topic: str = "Démarrage rapide"):
        super().__init__(parent)
        en = i18n.LANG == "en"
        self.setWindowTitle("Aide — Floppy Studio")
        self.resize(900, 620)
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        self.list = QListWidget()
        self.list.setFixedWidth(220)
        self.keys = list(FR)
        for k in self.keys:
            self.list.addItem(TOPICS_EN[k] if en else k)
        self.view = QTextBrowser()
        self.view.setObjectName("help")
        self.view.setOpenExternalLinks(True)
        h.addWidget(self.list)
        h.addWidget(self.view, 1)
        v.addLayout(h, 1)
        b = QPushButton("Fermer")
        b.clicked.connect(self.accept)
        v.addWidget(b, 0, Qt.AlignRight)
        self.src = EN if en else FR
        self.en = en
        self.list.currentRowChanged.connect(self._show)
        self.list.setCurrentRow(self.keys.index(topic) if topic in self.keys else 0)

    def _show(self, i):
        k = self.keys[i]
        self.view.setHtml(shortcuts_html(self.en) if k == "Raccourcis clavier" else self.src[k])
