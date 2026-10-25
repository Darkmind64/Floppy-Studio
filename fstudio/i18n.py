"""Traduction de l'interface (français → anglais), appliquée à la volée.

Les textes sont écrits en français dans le code ; en mode anglais, les accesseurs Qt
(setText, setToolTip, addItem…) sont interceptés et chaque widget est traduit à sa
première apparition. Les phrases composées sont traduites par fragments connus.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

LANG = "fr"

# « français<TAB>anglais », une paire par ligne ; \n = saut de ligne
PAIRS = r"""
mauvaise (démagnétisation, moisissure ou rayure)	poor (demagnetised, mould or scratches)
moyenne (support fatigué)	fair (worn media)
excellente	excellent
bonne	good
Taille	Size
Speedlock, Copylock, Macrodos/fuzzy bits	Speedlock, Copylock, Macrodos/fuzzy bits
Piste avec signal mais non décodable en AmigaDOS	Track with signal but not decodable as AmigaDOS
loader maison / protection (Copylock, format de jeu propriétaire)	custom loader / protection (Copylock, proprietary game format)
Données présentes au-delà de la piste 79	Data present beyond track 79
pistes supplémentaires	extra tracks
Copylock ST, protections à secteurs fantômes	Copylock ST, phantom-sector protections
format à tailles mixtes	mixed sector sizes
protections par faux ID	fake-ID protections
CRC volontairement faux (Speedlock, Alkatraz) ou défaut local	deliberate bad CRC (Speedlock, Alkatraz) or local defect
protection par Deleted Data Mark	Deleted Data Mark protection
piste surchargée	overloaded track
Secteur(s) faible(s) (contenu variable d'un tour à l'autre) : 	Weak sector(s) (content varies between revolutions):
Piste dense / longue : 	Dense / long track:
 % de transitions	 % transitions
Débit de cellule différent (	Different cell rate (
IDs de secteur dupliqués : 	Duplicate sector IDs:
Tailles de secteur non standard : 	Non-standard sector sizes:
Numéros de piste falsifiés dans les en-têtes : 	Fake track numbers in headers:
Erreur CRC données sur 	Data CRC error on
 secteur(s) d'une piste par ailleurs lisible	 sector(s) of an otherwise readable track
 secteur(s) marqués « supprimés » (DAM F8)	 sector(s) marked "deleted" (DAM F8)
 secteurs au lieu de 	 sectors instead of
piste longue (Copylock Amiga, Rainbow Arts, Rob Northen)	long track (Copylock Amiga, Rainbow Arts, Rob Northen)
vitesse variable (Copylock, Speedlock « long track »)	variable speed (Copylock, Speedlock long track)
Titre	Title
Plateforme	Platform
Système	System
Étiquette	Label
Fichiers	Files
Illisibles	Unreadable
Chemin	Path
Notes	Notes
Ajouté	Added
Catalogue de la collection	Collection catalogue
Rechercher un titre, une étiquette, une note ou un nom de fichier…	Search a title, label, note or file name…
Contenu de l'image	Image contents
Fichiers trouvés	Files found
Toutes plateformes	All platforms
Exporter le catalogue	Export catalogue
Doublons	Duplicates
Fermer	Close
📂  Ouvrir	📂  Open
Ouvrir l'image dans l'explorateur	Open the image in the explorer
🗂  Doublons	🗂  Duplicates
Images identiques et fichiers en double	Identical images and duplicate files
🗑  Retirer	🗑  Remove
Retirer du catalogue (le fichier est conservé)	Remove from catalogue (file is kept)
Exporter le catalogue en CSV	Export the catalogue as CSV
Fichier	File
Image	Image
Fichiers trouvés (	Files found (
Groupe / titre	Group / title
Titres	Titles
Catalogue : 	Catalogue:
 image(s) introuvable(s) retirée(s)	 missing image(s) removed
Contenu — 	Contents —
Catalogue	Catalogue
Catalogue exporté : 	Catalogue exported:
Fichiers présents sur plusieurs images : 	Files present on several images:
Images identiques : 	Identical images:
 groupe(s)	 group(s)
 image(s) ajoutée(s) ou mise(s) à jour	 image(s) added or updated
Fichier introuvable	File not found
 résultat(s)	 result(s)
Retirer 	Remove
 image(s) du catalogue ?\n(les fichiers ne sont pas supprimés)	 image(s) from the catalogue?\n(files are not deleted)
Émulateur non configuré	Emulator not configured
Lecture	Reading
Écriture	Writing
Analyse	Analysis
Analyse d'image flux	Flux image analysis
Récupération	Recovery
Comparaison d'images	Image comparison
Attente d'une disquette	Waiting for a disk
Calibrage	Calibration
Mesure de vitesse	Speed measurement
Positionnement	Seek
Nettoyage des têtes	Head cleaning
Effacement	Erase
Réinitialisation	Reset
Vérification firmware	Firmware check
Mise à jour firmware	Firmware update
Conversion	Conversion
 secteur(s) récupéré(s), 	 sector(s) recovered,
 toujours illisible(s). Image mise à jour.	 still unreadable. Image updated.
 secteur(s) diffèrent (	 sector(s) differ (
Délai d'attente dépassé.	Timed out.
Calibrage en cours — réglez le lecteur en observant la qualité ; Annuler pour arrêter.	Calibrating — adjust the drive while watching the quality; Cancel to stop.
Nettoyage terminé.	Cleaning done.
Greaseweazle réinitialisé (bus lecteur remis à zéro).	Greaseweazle reset (drive bus reset).
Lancement de la mise à jour du firmware…	Starting firmware update…
Modèle	Model
N° série	Serial no.
Échantillonnage	Sample rate
Lecture de 	Reading
Écriture de 	Writing
) — vérification : 	) — verify:
Vitesse lecteur : 	Drive speed:
Vitesse : 	Speed:
 tr/min — densité estimée : 	 rpm — estimated density:
Aucun format connu reconnu : disquette vierge, protégée ou format exotique (utiliser la capture flux brut).	No known format recognised: blank, protected or exotic disk (use raw flux capture).
Aucune protection ni anomalie détectée.	No protection or anomaly detected.
La taille de l'image ne correspond pas au format choisi.	The image size does not match the selected format.
 secteur(s) illisible(s) sur 	 unreadable sector(s) on
Rien à récupérer : l'image est complète.	Nothing to recover: the image is complete.
Insérez la disquette…	Insert the disk…
Vitesse : moyenne 	Speed: average
, écart 	, spread
Tête positionnée sur cylindre 	Head positioned on cylinder
 pistes effacées.	 tracks erased.
Aucun Greaseweazle connecté.	No Greaseweazle connected.
Mise à jour terminée, Greaseweazle reconnecté.	Update done, Greaseweazle reconnected.
Le périphérique a refusé la connexion.	The device refused the connection.
Opération annulée.	Operation cancelled.
Annulé	Cancelled
Le périphérique a interrompu l'opération.	The device interrupted the operation.
Format inconnu : 	Unknown format:
 : hors du format, ignorée	: outside the format, skipped
Flux capturé : 	Flux captured:
Écriture terminée : 	Write finished:
 piste(s) en échec.	 track(s) failed.
Format probable : 	Likely format:
Qualité moyenne du signal : 	Average signal quality:
Comparaison brute : 	Raw comparison:
 bloc(s) de 512 o différent(s)	 differing 512-byte block(s)
 (retirez d'abord la précédente)	 (remove the previous one first)
Info lecteur : 	Drive info:
Passe 	Pass
 terminée	 done
Conversion terminée → 	Conversion done →
Commande refusée par le Greaseweazle : 	Command refused by the Greaseweazle:
Erreur de communication : 	Communication error:
Erreur inattendue : 	Unexpected error:
Type de bus non supporté par ce matériel.	Bus type not supported by this hardware.
Lecture parfaite : 	Perfect read:
Lecture terminée avec 	Read finished with
 % récupérés).	 % recovered).
 : échec de vérification, nouvel essai 	: verify failed, retry
Écriture terminée en 	Write finished in
Fusion avec 	Merge with
 secteur(s) récupéré(s)	 sector(s) recovered
Disquette détectée.	Disk detected.
La mise à jour a échoué (voir journal).	Update failed (see log).
Mise à jour terminée ; reconnexion impossible : 	Update done; reconnection failed:
 : écrite et vérifiée	: written and verified
 : écrite	: written
 : ÉCHEC de vérification	: VERIFY FAILED
 pistes vérifiées.	 tracks verified.
 récupéré à la passe 	 recovered on pass
 contenu différent	 different content
 illisible dans les deux	 unreadable in both
lisible seulement dans A	readable only in A
lisible seulement dans B	readable only in B
 pistes identiques ; 	 identical tracks;
 lisibles seulement dans A, 	 readable only in A,
 seulement dans B)	 only in B)
Hexa + texte	Hex + text
Hexa seul	Hex only
Texte seul	Text only
▶  Lire	▶  Play
↩  Retour à la ligne	↩  Word wrap
Jeu :	Charset:
Libre	Free
Occupé sans fichier	Used, no file
Illisible	Unreadable
Octets à ignorer au début (en-tête)	Bytes to skip at start (header)
Rechercher dans l'image	Search in image
Texte, ou octets hexa (ex. 4E 71 00)	Text, or hex bytes (e.g. 4E 71 00)
🔎  Rechercher	🔎  Search
Éditeur de secteurs	Sector editor
✔  Appliquer au secteur	✔  Apply to sector
📤  Écrire cette piste sur la disquette	📤  Write this track to disk
Émulateurs	Emulators
🔎  Détection automatique	🔎  Auto-detect
Exécutable de l'émulateur	Emulator executable
Programmes (*.exe)	Programs (*.exe)
Détection	Detection
Aucune image ouverte	No image open
Ouvrez une image (IMG, ADF, ST, D64, FD, DSK, HFE, SCP…) ou lisez une disquette.	Open an image (IMG, ADF, ST, D64, FD, DSK, HFE, SCP…) or read a disk.
💾  Exporter…	💾  Export…
Exporte la sélection (ou tout le disque si rien n'est sélectionné)	Exports the selection (or the whole disk if nothing is selected)
🖼  Exporter converti…	🖼  Export converted…
Image → PNG, son → WAV, BASIC/texte → TXT	Image → PNG, sound → WAV, BASIC/text → TXT
↗  Ouvrir avec Windows	↗  Open with Windows
▶  Exécuter	▶  Run
🕹  Lancer l'image dans l'émulateur	🕹  Boot image in emulator
Configurer les émulateurs	Configure emulators
Filtrer…	Filter…
➕  Ajouter des fichiers…	➕  Add files…
Copie des fichiers dans l'image (ou glissez-les sur l'arborescence)	Copy files into the image (or drop them on the tree)
📁  Nouveau dossier	📁  New folder
🗑  Supprimer	🗑  Delete
💾  Enregistrer l'image sous…	💾  Save image as…
📤  Écrire sur la disquette	📤  Write to disk
🗺  Occupation	🗺  Usage map
Carte d'occupation du volume (clic : sélectionne le fichier)	Volume usage map (click selects the file)
🔎  Rechercher…	🔎  Search…
Recherche d'un texte ou d'octets dans les fichiers et toute l'image	Search text or bytes in files and the whole image
🧩  Secteurs…	🧩  Sectors…
Éditeur hexadécimal des secteurs, écriture d'une piste sur la disquette	Hex sector editor, write a track to disk
Aperçu	Preview
Analyse de l'image…	Analysing image…
Contenu brut du disque	Raw disk contents
Hexa	Hex
Propriétés	Properties
Exporter vers…	Export to…
Exporter converti	Export converted
Ajouter des fichiers	Add files
Nouveau dossier	New folder
Nom (8.3) :	Name (8.3):
Enregistrer l'image	Save image
Occupation	Usage
Secteur modifié (image non enregistrée)	Sector modified (image not saved)
Jeu de caractères :	Character set:
 octets non affichés)	 bytes not shown)
Affichage :	View:
Unité 	Unit
Processeur :	CPU:
Adresse :	Address:
Décalage :	Offset:
Texte (sans casse)	Text (case-insensitive)
Texte exact	Exact text
Hexadécimal	Hexadecimal
Emplacement	Location
Position	Position
Contexte	Context
 occurrence(s). Double-clic : ouvrir le fichier.	 match(es). Double-click: open the file.
Piste	Track
Face	Side
Secteur	Sector
Modifiez les octets hexadécimaux (la colonne texte est ignorée), puis « Appliquer ». L'image n'est modifiée sur disque qu'à l'enregistrement.	Edit the hex bytes (the text column is ignored), then "Apply". The image file is only changed when saved.
Éditeur	Editor
Chemins des émulateurs et arguments. Variables : {image}, {file}, {dir}.	Emulator paths and arguments. Variables: {image}, {file}, {dir}.
Exécutable	Executable
Arguments (image)	Arguments (image)
Arguments (fichier)	Arguments (file)
Double-clic sur « Exécutable » pour choisir le fichier.	Double-click "Executable" to pick the file.
Aucun nouvel émulateur trouvé dans les emplacements usuels.	No new emulator found in the usual locations.
Nom	Name
Type	Type
Date	Date
Impossible de lire l'image : 	Cannot read image:
Explorateur : 	Explorer:
Supprimés	Deleted
● modifiée (non enregistrée)	● modified (not saved)
 fichier(s) exporté(s) vers 	 file(s) exported to
Ouvert : 	Opened:
Émulateur	Emulator
Aucun émulateur prévu pour cette plateforme.	No emulator available for this platform.
Ajout	Add
Listing BASIC	BASIC listing
Supprimer	Delete
Supprimé : 	Deleted:
Image enregistrée : 	Image saved:
Carte non disponible pour ce système de fichiers.	Map not available for this file system.
Occupation — 	Usage —
Secteurs	Sectors
Géométrie inconnue pour cette image.	Unknown geometry for this image.
Enregistrez d'abord les modifications de fichiers.	Save the file changes first.
Format d'écriture inconnu pour cette image.	Unknown write format for this image.
Hexadécimal invalide.	Invalid hexadecimal.
Image brute	Raw image
 octets au lieu de 	 bytes instead of
Image modifiée	Image modified
Les modifications de l'image ouverte ne sont pas enregistrées. Les abandonner ?	Changes to the open image are not saved. Discard them?
. Format propriétaire, protégé ou disquette vierge : utilisez l'onglet Hexa.	. Proprietary, protected or blank disk: use the Hex tab.
 — système de fichiers non reconnu	 — file system not recognised
Fichiers supprimés (	Deleted files (
Attributs	Attributes
Modification possible pour FAT (PC, Atari ST, MSX, synthés), Amstrad CPC, Amiga, Thomson et Commodore 1541/1581	Editing available for FAT (PC, Atari ST, MSX, synths), Amstrad CPC, Amiga, Thomson and Commodore 1541/1581
Export	Export
Exporté : 	Exported:
Aucun émulateur 	No emulator
 configuré (	 configured (
).\n\nLancer la détection automatique ?\n\nTéléchargement : 	).\n\nRun auto-detection?\n\nDownload:
Lancement de 	Launching
 avec 	 with
Exécution	Run
Ajouté : 	Added:
 est un listing texte.\nLe convertir en BASIC tokenisé (chargement plus rapide, format natif) ?\nNon : copié tel quel en ASCII.	 is a text listing.\nConvert it to tokenised BASIC (faster loading, native format)?\nNo: copied as ASCII.
Supprimer 	Delete
 élément(s) de l'image ?\n(l'image d'origine n'est modifiée qu'à l'enregistrement)	 item(s) from the image?\n(the original image is only changed when saved)
Enregistrer	Save
système (amorce, FAT, répertoire…)	system (boot, FAT, directory…)
occupé (aucun fichier connu : perdu ou réservé)	used (no known file: lost or reserved)
 unité(s) de 	 unit(s) of
, contigu	, contiguous
 fragments	 fragments
Octets invalides : 	Invalid bytes:
Aucun système de fichiers reconnu	No file system recognised
 secteur(s) illisible(s)	 unreadable sector(s)
Attributs : 	Attributes:
 endommagé(s)	 damaged
 fichier(s)	 file(s)
Erreur	Error
Image (	Image (
Audio	Audio
Export impossible : 	Export failed:
Erreur : 	Error:
Lancement impossible : 	Cannot launch:
Exécution de 	Running
L'émulateur démarre avec la disquette.\n\n	The emulator boots with the disk.\n\n
Dossier créé : 	Folder created:
■  Stop	■  Stop
Contenu	Contents
Désassemblage	Disassembly
Démarrez sur la disquette puis lancez le programme depuis le Shell.	Boot the disk then start the program from the Shell.
Lecture impossible : 	Cannot read:
Texte	Text
Tapez : RUN"	Type: RUN"
Ouvrez le lecteur A: puis double-cliquez 	Open drive A: then double-click
Tapez : LOADM"	Type: LOADM"
Auto-détection (scan IBM MFM/FM)	Auto-detect (IBM MFM/FM scan)
Image secteurs brute (IMG/IMA)	Raw sector image (IMG/IMA)
Image secteurs brute	Raw sector image
Atari ST compressée (MSA)	Compressed Atari ST (MSA)
SuperCard Pro (flux brut)	SuperCard Pro (raw flux)
KryoFlux stream (flux brut)	KryoFlux stream (raw flux)
Apple II ordre DOS	Apple II DOS order
Apple II ordre ProDOS	Apple II ProDOS order
Flux brut (générique)	Raw flux (generic)
Flux brut (aucun décodage)	Raw flux (no decoding)
Sampleurs & synthés	Samplers & synths
Flux brut / archivage	Raw flux / archiving
Toutes les images (	All images (
Autres systèmes	Other systems
Auto (scan) – 40 pistes, 1 face	Auto (scan) – 40 tracks, 1 side
Lecteur 3,5" : disquettes 3,5" formatées CPC (40 pistes).	3.5" drive: 3.5" disks formatted for CPC (40 tracks).
Auto (scan) – 80 pistes, 2 faces	Auto (scan) – 80 tracks, 2 sides
Formats étendus (Parados, Romdos, Vortex…).	Extended formats (Parados, Romdos, Vortex…).
Auto (scan) – 40 pistes, 2 faces	Auto (scan) – 40 tracks, 2 sides
Format PC 720 Ko (Yamaha, Korg… compatibles DOS)	PC 720 KB format (Yamaha, Korg… DOS-compatible)
Format PC 1,44 Mo (Kurzweil, Yamaha… compatibles DOS)	PC 1.44 MB format (Kurzweil, Yamaha… DOS-compatible)
Autre / propriétaire : flux brut	Other / proprietary: raw flux
Capture fidèle du flux, décodable plus tard.	Faithful flux capture, decodable later.
Programme S1000	S1000 program
Effets	Effects
Programme S3000	S3000 program
Programme S900	S900 program
 (expérimental)	 (experimental)
Blocs	Blocks
bloc de départ	start block
Supprimé — en-tête retrouvé	Deleted — header found
Bloc racine	Root block
Bootable	Bootable
Espace insuffisant : 	Not enough space:
 existe déjà	 already exists
Dossier	Folder
Binaire	Binary
Pistes	Tracks
Supprimé — 	Deleted —
Modification non prise en charge pour ce système	Editing not supported for this system
Enregistrement non pris en charge pour ce système	Saving not supported for this system
Racine	Root
Blocs libres	Free blocks
Répertoire plein	Directory full
Supprimé (scratch) — chaîne de secteurs	Deleted (scratched) — sector chain
BASIC protégé	Protected BASIC
Binaire protégé	Protected binary
Bloc	Block
Secteur absent (piste 	Missing sector (track
 Ko requis, 	 KB required,
 Ko libres	 KB free
Secteurs défectueux	Bad sectors
exécution	execution
partiellement écrasé	partly overwritten
récupérable	recoverable
Décodé avec 	Decoded with
Média	Media
secteur de démarrage illisible : géométrie standard supposée	unreadable boot sector: standard geometry assumed
FAT illisible : fichiers lus comme contigus	unreadable FAT: files read as contiguous
Attention	Warning
répertoire partiellement illisible : des fichiers peuvent manquer	directory partly unreadable: files may be missing
 (sans BPB, DOS 1.x)	 (no BPB, DOS 1.x)
récupération	recovery
clusters contigus supposés	contiguous clusters assumed
Sampleurs & synthés (DOS)	Samplers & synths (DOS)
DOS BASIC 320 Ko — 1 face	DOS BASIC 320 KB — 1 side
DOS BASIC 2 × 320 Ko — 2 faces	DOS BASIC 2 × 320 KB — 2 sides
AMSDOS Data (178 Ko, 40 pistes)	AMSDOS Data (178 KB, 40 tracks)
Pour un lecteur 3,5" branché en B: sur le CPC.	For a 3.5" drive connected as B: on the CPC.
AMSDOS Système / Vendor (169 Ko)	AMSDOS System / Vendor (169 KB)
Pistes système vides (pas de CP/M).	Empty system tracks (no CP/M).
AMSDOS IBM / CP/M (8 secteurs, 156 Ko)	AMSDOS IBM / CP/M (8 sectors, 156 KB)
Format IBM du CPC (compatible PC 160 Ko).	CPC IBM format (PC 160 KB compatible).
Vide	Empty
Programme BASIC	BASIC program
Données BASIC	BASIC data
Langage machine	Machine code
Source assembleur	Assembler source
Supprimé — 1er bloc seulement (chaînage effacé)	Deleted — first block only (chain erased)
données inversées	inverted data
Le firmware le plus récent va être téléchargé depuis GitHub et installé.\n\nNe débranchez pas le Greaseweazle pendant l'opération.	The latest firmware will be downloaded from GitHub and installed.\n\nDo not unplug the Greaseweazle during the operation.
Flux magnétique brut : aucune interprétation, archivage fidèle.	Raw magnetic flux: no interpretation, faithful archive.
Prêt	Ready
Rafraîchir la liste des ports	Refresh the port list
Connecter	Connect
Sélection du lecteur sur le câble	Drive selection on the cable
Déconnecté	Disconnected
Lire une disquette	Read a disk
Crée une image disque à partir de la disquette insérée.	Creates a disk image from the inserted disk.
Profil	Profile
Réglages enregistrés : format, relectures, pistes, dossier…	Saved settings: format, retries, tracks, folder…
Enregistrer les réglages actuels comme profil	Save current settings as a profile
Supprimer le profil sélectionné	Delete the selected profile
🔍  Détecter automatiquement	🔍  Auto-detect
Fichier de sortie	Output file
Choisir l'emplacement de l'image…	Choose where to save the image…
Garder aussi le flux brut (.scp)	Also keep the raw flux (.scp)
Archive fidèle de la disquette, utile pour récupérer\nplus tard des secteurs ou réessayer un autre format.	Faithful archive of the disk, useful to recover\nsectors later or try another format.
Analyse approfondie (protections)	Deep analysis (protections)
Décode chaque tour séparément et scanne les secteurs non standard.\nPlus lent ; un rapport s'affiche à la fin.	Decodes each revolution separately and scans non-standard sectors.\nSlower; a report is shown at the end.
Nom automatique horodaté	Automatic timestamped name
Options avancées	Advanced options
Révolutions lues par piste (auto = valeur du format)	Revolutions read per track (auto = format default)
Après échec des relectures : ramener la tête en piste 0 puis réessayer	After failed retries: return the head to track 0 and retry
Révolutions	Revolutions
Relectures	Retries
Repositionnements	Re-seeks
📥  Lire la disquette	📥  Read disk
📂  Explorer l'image lue	📂  Explore read image
♻  Re-décoder le flux sauvegardé…	♻  Re-decode saved flux…
Recrée une image à partir d'un flux brut (.scp, .hfe…) avec un autre format,\nsans relire la disquette	Rebuilds an image from a raw flux (.scp, .hfe…) with another format,\nwithout re-reading the disk
Lecture par lot	Batch reading
Enchaîner plusieurs disquettes	Read several disks in a row
Détecter l'insertion suivante	Detect next insertion
Utilise la ligne « disk change » du lecteur (broche 34) ;\nà défaut, détecte les impulsions d'index.	Uses the drive "disk change" line (pin 34);\notherwise detects index pulses.
— Réglages actuels —	— Current settings —
Profil de lecture	Read profile
Nom du profil :	Profile name:
Re-décoder un flux	Re-decode a flux
Flux brut (.scp, .hfe, .raw…)	Raw flux (.scp, .hfe, .raw…)
♻  Décoder et explorer	♻  Decode and explore
Écrire une disquette	Write a disk
Écrit une image sur la disquette insérée (contenu actuel écrasé).	Writes an image to the inserted disk (current content overwritten).
Image source	Source image
Choisir une image…	Choose an image…
Écrire le flux tel quel (SCP, HFE…)	Write flux as-is (SCP, HFE…)
Vérifier chaque piste après écriture	Verify each track after writing
Effacer chaque piste avant écriture	Erase each track before writing
Effacer les pistes absentes de l'image	Erase tracks missing from the image
Essais si échec	Retries on failure
Formater une disquette	Format a disk
Système de fichiers vierge sur la disquette, ou image vierge.	Blank file system on the disk, or blank image.
Système de fichiers	File system
Bas niveau (tous formats)	Low level (all formats)
Nom du volume	Volume name
facultatif	optional
Format bas niveau	Low-level format
Octet de remplissage	Fill byte
Pistes et secteurs écrits selon la géométrie choisie, sans système de fichiers.	Tracks and sectors written with the chosen geometry, no file system.
Utile pour une disquette d'un autre format ou d'une autre densité	Useful for a disk of another format or density
🧹  Formater la disquette	🧹  Format disk
💾  Créer une image vierge…	💾  Create blank image…
Image vierge pour émulateur, ou à remplir dans l'explorateur puis écrire	Blank image for emulators, or to fill in the explorer then write
Créer une image vierge	Create a blank image
Copier et vérifier	Copy and verify
Duplication, comparaison, test de surface.	Duplication, comparison, surface test.
Format de la disquette	Disk format
Copie de disquette	Disk copy
Vérifier l'écriture	Verify writing
Conserver l'image de la source	Keep the source image
Enregistre l'image lue dans le dossier des images (nom horodaté)	Saves the read image in the images folder (timestamped)
📑  Copier une disquette	📑  Copy a disk
Comparer avec une image	Compare with an image
Image de référence…	Reference image…
⚖  Lire et comparer	⚖  Read and compare
Test de surface	Surface test
🩺  Tester la surface	🩺  Test surface
Récupération des secteurs illisibles	Unreadable sector recovery
Image à compléter (IMG, ST, ADF, FD…)	Image to complete (IMG, ST, ADF, FD…)
Passes par piste	Passes per track
♻  Relire les secteurs illisibles	♻  Re-read unreadable sectors
🧬  Fusionner avec d'autres lectures…	🧬  Merge with other reads…
Comparer deux images	Compare two images
⚖  Comparer piste par piste	⚖  Compare track by track
🧬  Fusionner B dans une copie de A	🧬  Merge B into a copy of A
Crée « A_fusion » : secteurs illisibles de A remplacés par ceux de B	Creates "A_fusion": A's unreadable sectors replaced by B's
Vert : identique · orange : lisible d'un seul côté · rouge : différent.	Green: identical · orange: readable on one side only · red: different.
Comparaison…	Comparing…
Fusion A + B	Merge A + B
Autres lectures du même disque	Other reads of the same disk
Copie : lecture de la source	Copy: reading source
Comparaison : lecture	Compare: reading
Exporter la carte	Export map
Analyser	Analyse
Lit quelques pistes et identifie le format le plus probable.	Reads a few tracks and identifies the most likely format.
🔍  Analyser la disquette	🔍  Analyse disk
Résultat	Result
Vitesse (tr/min)	Speed (rpm)
Densité estimée	Estimated density
Format probable	Likely format
Utiliser ce format pour la lecture	Use this format for reading
Analyse complète (qualité, protections)	Full analysis (quality, protections)
🧪  Analyser toute la disquette	🧪  Analyse whole disk
Image flux…	Flux image…
🧪  Analyser l'image flux	🧪  Analyse flux image
Analyse complète	Full analysis
Rapport de la disquette	Disk report
💾  Exporter HTML / PDF…	💾  Export HTML / PDF…
Toutes vos images : recherche, notes, doublons.	All your images: search, notes, duplicates.
➕  Ajouter des images…	➕  Add images…
📁  Ajouter un dossier (récursif)…	📁  Add a folder (recursive)…
🧹  Retirer les images introuvables	🧹  Remove missing images
Ajout auto. des images lues/ouvertes	Auto-add read/opened images
Ajouter au catalogue	Add to catalogue
Dossier d'images	Image folder
Explorer	Explore
Parcourt les fichiers d'une image : aperçu, export, exécution.	Browse an image's files: preview, export, run.
📂  Ouvrir une image…	📂  Open an image…
📥  Lire et explorer la disquette	📥  Read and explore disk
Utilise le format choisi dans « Lire »	Uses the format chosen in "Read"
Explorer la dernière image lue	Explore last read image
Décodage des images flux (SCP, HFE, RAW…)	Flux image decoding (SCP, HFE, RAW…)
Détection automatique du codage	Automatic encoding detection
Images récentes	Recent images
⚙  Configurer les émulateurs…	⚙  Configure emulators…
Ouvrir une image	Open an image
Outils du lecteur	Drive tools
Diagnostic et maintenance.	Diagnostics and maintenance.
Vitesse de rotation	Rotation speed
Mesurer	Measure
Un lecteur 3,5" sain tourne à 300 tr/min ±1,5 %.	A healthy 3.5" drive spins at 300 rpm ±1.5 %.
Calibrage / alignement	Calibration / alignment
Pistes « cylindre.face » lues à tour de rôle	"cylinder.side" tracks read in turn
▶  Démarrer	▶  Start
Qualité > 97 % : excellent · 92–97 % : correct · < 90 % : réglage ou support à vérifier.	Quality > 97 %: excellent · 92–97 %: fair · < 90 %: check alignment or media.
Déplacer la tête	Move the head
Aller	Go
Piste 0	Track 0
Nettoyage des têtes	Head cleaning
Nettoyer	Clean
Effacer la disquette	Erase disk
Réinitialiser	Reset
Vérifier firmware	Check firmware
Mettre à jour…	Update…
Convertir	Convert
Convertit une image vers un autre format (sans le lecteur).	Converts an image to another format (no drive needed).
Image disque	Disk image
Destination	Destination
Format de décodage	Decoding format
🔁  Convertir l'image	🔁  Convert image
Conversion de fichiers	File conversion
Fichier source…	Source file…
Tramage des images (Floyd-Steinberg)	Image dithering (Floyd-Steinberg)
🔁  Convertir le fichier…	🔁  Convert file…
Choisir un fichier	Choose a file
Dossier de destination	Destination folder
Appareil	Device
Informations sur le Greaseweazle connecté.	Information about the connected Greaseweazle.
Carte de la disquette	Disk map
Santé	Health
Colore les pistes selon la qualité du signal magnétique\n(violet : secteurs faibles)	Colours tracks by magnetic signal quality\n(purple: weak sectors)
Rapport : protections, anomalies, export HTML / PDF	Report: protections, anomalies, HTML / PDF export
Exporter la carte en PNG	Export the map as PNG
Secteurs OK	Sectors OK
Écoulé / restant	Elapsed / left
Détail de la piste	Track details
Survolez ou cliquez une piste.	Hover or click a track.
Journal	Log
Effacer	Clear
Enregistrer…	Save…
Annuler	Cancel
Enregistrer le journal	Save log
Texte (*.txt)	Text (*.txt)
Depuis un fichier .upd…	From a .upd file…
Terminé	Done
Plusieurs images	Several images
Conversion par lot	Batch conversion
🔁  Convertir	🔁  Convert
Lecteur A (PC, après torsade)	Drive A (PC, after twist)
Lecteur B (PC, avant torsade)	Drive B (PC, before twist)
Lecteur	Drive
Lire	Read
Écrire	Write
Formater	Format
Copier	Copy
Outils	Tools
Profil « 	Profile "
 » enregistré	" saved
 » appliqué	" applied
Choisissez un flux et un format décodé.	Choose a flux and a decoded format.
Décodage ← 	Decoding ←
Lot : retirez la disquette et insérez la suivante (Annuler pour terminer).	Batch: remove the disk and insert the next one (Cancel to stop).
En attente de la disquette suivante	Waiting for the next disk
 disquette(s) lue(s).<br>Insérez la disquette suivante puis <b>Oui</b>, ou <b>Non</b> pour terminer.	 disk(s) read.<br>Insert the next disk then <b>Yes</b>, or <b>No</b> to finish.
 disquette(s) lue(s).	 disk(s) read.
Confirmer le formatage	Confirm formatting
Formatage — 	Formatting —
Image vierge créée : 	Blank image created:
Image créée. L'ouvrir dans l'explorateur pour y ajouter des fichiers ?	Image created. Open it in the explorer to add files?
Connectez d'abord le Greaseweazle.	Connect the Greaseweazle first.
Confirmer l'écriture	Confirm writing
Lit la disquette source, puis demande d'insérer la disquette de destination. Choisissez « Flux brut » pour copier les disquettes protégées.	Reads the source disk, then asks for the destination disk. Choose "Raw flux" to copy protected disks.
Lit toute la disquette sans rien enregistrer et affiche les secteurs faibles ou illisibles sur la carte.	Reads the whole disk without saving anything and shows weak or unreadable sectors on the map.
Relit uniquement les secteurs manquants d'une image (format ci-dessus), en plusieurs passes avec repositionnement de la tête, et complète l'image. Ou fusionne plusieurs lectures du même disque (lecteurs différents…).	Re-reads only the missing sectors of an image (format above), in several passes with head re-seeking, and completes the image. Or merges several reads of the same disk (different drives…).
Choisissez les deux images.	Choose both images.
Comparaison 	Comparing
Choisissez les deux images (brutes) et leur format exact dans « Format de la disquette ».	Choose both (raw) images and their exact format in "Disk format".
Choisissez l'image à compléter.	Choose the image to complete.
Choisissez le format exact de l'image (pas « scan » ni flux).	Choose the exact image format (not "scan" or flux).
Seules les images secteurs brutes (IMG, ST, ADF, FD, D81…) peuvent être complétées.	Only raw sector images (IMG, ST, ADF, FD, D81…) can be completed.
Récupération ← 	Recovery ←
Fusion de lectures	Merging reads
Choisissez l'image de référence.	Choose the reference image.
Choisissez le format décodé de la disquette.	Choose the disk's decoded format.
✔ Identique : 	✔ Identical:
 secteurs comparés.	 sectors compared.
 secteur(s) sur 	 sector(s) out of
 diffèrent (	 differ (
Lit toute la disquette au format choisi dans « Lire », mesure la qualité du signal piste par piste et recherche les protections (secteurs faibles, tailles non standard, pistes longues, IDs falsifiés…).	Reads the whole disk with the format chosen in "Read", measures signal quality track by track and looks for protections (weak sectors, non-standard sizes, long tracks, fake IDs…).
Ou une image flux existante (SCP, HFE, KryoFlux…) sans lecteur :	Or an existing flux image (SCP, HFE, KryoFlux…) without a drive:
Choisissez une image flux.	Choose a flux image.
Analyse ← 	Analysis ←
Aucune piste lue ou analysée pour l'instant.	No track read or analysed yet.
Secteurs lisibles	Readable sectors
Secteurs illisibles	Unreadable sectors
Pistes relues	Re-read tracks
Vitesse moyenne	Average speed
Qualité moyenne	Average quality
Pire piste	Worst track
Protections et anomalies : 	Protections and anomalies:
aucune	none
Constat	Finding
Schémas possibles	Possible schemes
Exporter le rapport	Export report
Page web (*.html);;PDF (*.pdf)	Web page (*.html);;PDF (*.pdf)
Double-clic sur une image ou un fichier trouvé : ouverture dans l'explorateur. Le titre et les notes se modifient directement dans le tableau. La base est enregistrée dans le profil Windows de l'utilisateur.	Double-click an image or a found file to open it in the explorer. Title and notes can be edited directly in the table. The database is stored in the user's Windows profile.
Systèmes reconnus : 	Supported systems:
Fichier introuvable.	File not found.
Aucune image lue récemment.	No recently read image.
Lit en boucle des pistes de référence d'une disquette saine au format choisi dans « Lire » et affiche la qualité du signal en direct : utile pour régler l'alignement radial (vis de la tête) ou comparer des lecteurs. Annuler pour arrêter.	Repeatedly reads reference tracks of a healthy disk in the format chosen in "Read" and shows signal quality live: useful to adjust radial alignment (head screw) or compare drives. Cancel to stop.
Face 0	Side 0
Face 1	Side 1
Insérer une disquette de nettoyage (humidifiée) avant de lancer.	Insert a (moistened) cleaning disk before starting.
Efface magnétiquement toutes les pistes (contenu définitivement perdu).	Magnetically erases all tracks (content permanently lost).
2 faces, 80 cyl.	2 sides, 80 cyl.
Face 0, 80 cyl.	Side 0, 80 cyl.
2 faces, 84 cyl.	2 sides, 84 cyl.
Requis pour passer d'un flux (SCP, HFE…) à une image secteurs (IMG, ADF…).	Required to go from a flux (SCP, HFE…) to a sector image (IMG, ADF…).
Texte → BASIC CPC (Locomotive)	Text → CPC BASIC (Locomotive)
Texte → MSX-BASIC	Text → MSX-BASIC
Texte → GW-BASIC (PC)	Text → GW-BASIC (PC)
Image → écran CPC mode 0 (16 coul.)	Image → CPC screen mode 0 (16 col.)
Image → écran CPC mode 1 (4 coul.)	Image → CPC screen mode 1 (4 col.)
Image → écran CPC mode 2 (2 coul.)	Image → CPC screen mode 2 (2 col.)
WAV → sample Akai S1000 (expér.)	WAV → Akai S1000 sample (exp.)
Le résultat peut ensuite être ajouté à une image dans l'explorateur. Pour un écran CPC, un chargeur BASIC (encres + LOAD) est créé à côté.	The result can then be added to an image in the explorer. For a CPC screen, a BASIC loader (inks + LOAD) is created alongside.
Choisissez le fichier source.	Choose the source file.
Astuce : sur un câble PC à torsade, le lecteur branché après la torsade est le lecteur A. Un lecteur 3,5" seul sur un câble droit se pilote généralement en Shugart DS0 ou DS1.	Tip: on a twisted PC cable, the drive after the twist is drive A. A single 3.5" drive on a straight cable is usually driven as Shugart DS0 or DS1.
En-tête	Header
Données	Data
Aucun port série	No serial port
Déconnecté.	Disconnected.
Connecté à 	Connected to
 sur 	 on
Le Greaseweazle est en mode mise à jour : seule la mise à jour du firmware est possible.	The Greaseweazle is in update mode: only a firmware update is possible.
Déconnecter	Disconnect
Une opération est déjà en cours.	An operation is already running.
Annulation…	Cancelling…
Lecture → 	Reading →
Choisissez une image à écrire.	Choose an image to write.
Sélectionnez le format de l'image.	Select the image format.
Écriture ← 	Writing ←
Disquette de nettoyage insérée ?	Cleaning disk inserted?
Toutes les données de la disquette seront perdues. Continuer ?	All data on the disk will be lost. Continue?
Fichier de mise à jour	Update file
Choisissez une source et une destination.	Choose a source and a destination.
Conversion → 	Conversion →
Aucune image disquette reconnue dans le dépôt.	No disk image recognised in the drop.
📚  Ajouter au catalogue	📚  Add to catalogue
🔁  Convertir toutes vers un format…	🔁  Convert all to a format…
📂  Ouvrir la première dans l'explorateur	📂  Open the first one in the explorer
Format de sortie (l'extension du préréglage est utilisée) :	Output format (the preset's extension is used):
Conversion par lot : 	Batch conversion:
 restante(s))	 left)
Connecté	Connected
Lot terminé : 	Batch finished:
Choisissez un format décodé (pas un flux brut).	Choose a decoded format (not raw flux).
Géométrie inconnue pour ce format.	Unknown geometry for this format.
La disquette va être <b>entièrement effacée</b> et formatée en :<br><br><b>	The disk will be <b>completely erased</b> and formatted as:<br><br><b>
</b><br><br>Vérifiez que la disquette n'est pas protégée en écriture.	</b><br><br>Make sure the disk is not write-protected.
Écrire <code>	Write <code>
</code> sur la disquette (format 	</code> to the disk (format
) ?<br>Le contenu actuel sera remplacé.	)?<br>The current content will be replaced.
Carte exportée : 	Map exported:
Matériel	Hardware
Rapport — 	Report —
Rapport exporté : 	Report exported:
Image introuvable :\n	Image not found:\n
Mesures	Samples
Cylindre	Cylinder
Passes	Passes
Converti : 	Converted:
Grille	Grid
Disque	Disk
Aucun appareil connecté.	No device connected.
<br>Format(s) correspondant à la taille : 	<br>Format(s) matching the size:
Extension de fichier non reconnue.	Unrecognised file extension.
Le contenu de la disquette va être <b>définitivement remplacé</b> par :<br><br><code>	The disk content will be <b>permanently replaced</b> by:<br><br><code>
<br><br>Vérifiez que la disquette n'est pas protégée en écriture (volet fermé).	<br><br>Make sure the disk is not write-protected (shutter closed).
Pistes invalides (format : 0.0, 40.1…).	Invalid tracks (format: 0.0, 40.1…).
Relectures : 	Retries:
Signal : 	Signal:
Flux piste 	Flux track
 image(s)</b> déposée(s). Que faire ?	 image(s)</b> dropped. What now?
Une opération est en cours. Interrompre et quitter ?	An operation is running. Stop it and quit?
Copie : écriture de la destination	Copy: writing destination
Comparaison impossible : 	Comparison failed:
Conversion impossible : 	Conversion failed:
Connexion impossible (	Connection failed (
Choisissez le format manuellement.	Choose the format manually.
 existe déjà. Remplacer ?	 already exists. Replace?
Spécification de pistes invalide : 	Invalid track specification:
conforme	within tolerance
hors tolérance : réglage ou courroie à vérifier	out of tolerance: check adjustment or belt
Secteurs 	Sectors
 — illisibles : 	 — unreadable:
 · supprimé	 · deleted
Copie	Copy
Lecture terminée.<br><br>Insérez la disquette de <b>destination</b> (son contenu sera remplacé), puis cliquez OK.	Read finished.<br><br>Insert the <b>destination</b> disk (its content will be replaced), then click OK.
 différent	 different
Encres CPC : 	CPC inks:
Sample Akai : 	Akai sample:
 échantillons à 	 samples at
Moyenne 	Average
✔ Images identiques.	✔ Identical images.
 différence(s) — 	 difference(s) —
 secteur(s) lisibles seulement dans A, 	 sector(s) readable only in A,
 seulement dans B. Voir la carte.	 only in B. See the map.
 piste(s) n'ont pas pu être vérifiées.\nDisquette probablement abîmée.	 track(s) could not be verified.\nDisk probably damaged.
Test de surface : 	Surface test:
 secteurs lisibles	 readable sectors
 — pistes en échec : 	 — failed tracks:
En attente	Pending
En cours	In progress
Vérifiée	Verified
OK après relecture	OK after retry
Écrite	Written
Échec	Failed
Aucun secteur	No sector
Flux capturé	Flux captured
Effacée	Erased
Ignorée	Skipped
Fusion	Merge
Segment texte	Text segment
Segment données	Data segment
Symboles	Symbols
Drapeaux	Flags
Adresse de chargement	Load address
Longueur	Length
contenu binaire : affichage forcé	binary content: forced display
Tailles	Sizes
Taille chargée	Loaded size
Mémoire min/max	Memory min/max
Début	Start
Fin	End
Format étendu	Extended format
programme .COM chargé en 0100h	.COM program loaded at 0100h
Histogramme des intervalles de flux	Flux interval histogram
Cliquez une piste lue pour voir son flux	Click a read track to see its flux
Aucune mesure	No measurement
Non lue	Not read
Hors sélection	Not selected
Secteurs : 	Sectors:
Qualité du signal : 	Signal quality:
Secteurs faibles : 	Weak sectors:
Secteur #	Sector #
ILLISIBLE	UNREADABLE
Cylindre 	Cylinder
 · face 	 · side
 — pas encore lue.	 — not read yet.
 tr/min	 rpm
 transitions	 transitions
 · gigue 	 · jitter
 · cellule 	 · cell
Contenu	Contents
Secteurs illisibles 	Unreadable sectors
Libre	Free
Fichiers : 	Files:
Pistes : 	Tracks:
Secteurs : 	Sectors:
Préférences	Preferences
Langue	Language
Thème	Theme
Sombre	Dark
Clair	Light
Vérifier les mises à jour au démarrage	Check for updates at startup
Redémarrer maintenant	Restart now
Plus tard	Later
Redémarrage nécessaire	Restart required
La langue et le thème seront appliqués au prochain démarrage.	Language and theme will be applied at next start.
Aide	Help
⚙  Préférences…	⚙  Preferences…
🔄  Rechercher des mises à jour	🔄  Check for updates
❓  Aide	❓  Help
ℹ  À propos	ℹ  About
⌨  Raccourcis clavier	⌨  Keyboard shortcuts
Mise à jour disponible	Update available
 disponible	 available
Version installée : 	Installed version:
Ignorer cette version	Skip this version
Installer maintenant	Install now
Recherche de mises à jour…	Checking for updates…
Mises à jour	Updates
Impossible de joindre GitHub :\n	Cannot reach GitHub:\n
Vous utilisez la dernière version (	You are using the latest version (
Téléchargement de 	Downloading
Mise à jour	Update
Échec du téléchargement : 	Download failed:
Impossible de lancer l'installateur : 	Cannot start the installer:
Pas de notes de version.	No release notes.
Version 	Version
Sommaire	Contents
Format actif	Active format
🔍  Détecter	🔍  Detect
Analyse la disquette insérée et choisit le format le plus probable	Analyses the inserted disk and picks the most likely format
Modifiable dans la barre « Format actif » en haut.	Can be changed in the "Active format" bar at the top.
Format de lecture	Read format
Format d'écriture	Write format
Géométrie	Geometry
Sinon	Otherwise
Disquette	Disk
Matériel	Hardware
Images flux : le format actif est alors ignoré	Flux images: the active format is then ignored
Décochez pour décoder les flux avec le format actif	Uncheck to decode flux with the active format
Connectez d'abord le Greaseweazle (bouton « Connecter » en haut).	Connect the Greaseweazle first ("Connect" button at the top).
Masquer	Hide
 — lecture parfaite	 — perfect read
📂  Explorer	📂  Explore
📁  Dossier	📁  Folder
📋  Rapport	📋  Report
♻  Récupérer	♻  Recover
📤  Écrire une copie	📤  Write a copy
Écriture terminée (	Write finished (
 piste(s) vérifiée(s))	 track(s) verified)
📥  Relire	📥  Read again
Conversion terminée : 	Conversion finished: 
 · image 	 · image 
 · pistes 	 · tracks 
 Ko	 KB
 Mo	 MB
1 face	1 side
2 faces	2 sides
 faces	 sides
 face	 side
 cyl × 	 cyl × 
secteurs/piste	sectors/track
 secteurs/piste	 sectors/track
Pistes : 	Tracks: 
DD 1 face	DD 1 side
Fichier(s)	File(s)
Binaire AMSDOS chargé en 	AMSDOS binary loaded at 
chargé en 	loaded at 
Chargé en 	Loaded at 
, exécution 	, execution 
Systèmes reconnus : FAT12/16 (PC, Atari ST, MSX, synthés DOS), AmigaDOS OFS/FFS, Commodore 1541/1571/1581, DOS BASIC Thomson, Amstrad CPC (AMSDOS/CP/M), Apple II DOS 3.3/ProDOS, Akai S900/S1000/S3000 (expérimental).	Supported systems: FAT12/16 (PC, Atari ST, MSX, DOS synths), AmigaDOS OFS/FFS, Commodore 1541/1571/1581, Thomson DOS BASIC, Amstrad CPC (AMSDOS/CP/M), Apple II DOS 3.3/ProDOS, Akai S900/S1000/S3000 (experimental).
Programme DOS .COM (CS:0100)	DOS .COM program (CS:0100)
Binaire Apple II chargé en 	Apple II binary loaded at 
Exécutable MZ, en-tête 	MZ executable, header 
Exécutable AmigaDOS : premier hunk CODE	AmigaDOS executable: first CODE hunk
Programme TOS : segment texte 	TOS program: text segment 
Programme CP/M (.COM)	CP/M program (.COM)
 o, point d'entrée 	 B, entry point 
Bloc 	Block 
Exécutable	Executable
Exécution	Execution
Chargement	Load address
Fichiers supprimés	Deleted files
Supprimé	Deleted
utilisateur	user
blocs	blocks
commentaire	comment
nom 8.3	8.3 name
Ouvrir	Open
Sauvegarder	Save
 secteurs	 sectors
 pistes en 	 tracks in 
 pistes	 tracks
 secteur(s)	 sector(s)
 piste(s)	 track(s)
 fichier(s) · 	 file(s) · 
"""

_EXACT: Dict[str, str] = {}
_RX = None
_FMAP: Dict[str, str] = {}
_FRAGS: List[Tuple[str, str]] = []
_CACHE: Dict[str, str] = {}


def _load():
    for line in PAIRS.split("\n"):
        if "\t" not in line:
            continue
        fr, en = line.split("\t", 1)
        fr, en = fr.replace("\\n", "\n"), en.replace("\\n", "\n")
        if fr.endswith(" ") and not en.endswith(" "):
            en += " "
        if fr.startswith(" ") and not en.startswith(" "):
            en = " " + en
        _EXACT[fr] = en
        if len(fr.strip()) >= 4 or (fr.startswith(" ") and len(fr) >= 3):
            _FRAGS.append((fr, en))
    _FRAGS.sort(key=lambda x: -len(x[0]))
    global _RX, _FMAP
    _FMAP = dict(_FRAGS)
    _RX = re.compile("|".join(re.escape(fr) for fr, _ in _FRAGS))


_load()
_FR_HINT = re.compile(r"[éèêàùçôîâœÉÈÀ]|\b(le|la|les|des|du|une|et|ou|pour|avec|sur|sans|par|aucun|Ko|Mo|"
                      r"faces?|pistes?|secteurs?|fichiers?|image|lecture|écriture|disquette|Lecteur|Face)\b",
                      re.I)


def tr(s):
    """Traduit un texte (exact, puis par fragments)."""
    if LANG == "fr" or not isinstance(s, str) or not s:
        return s
    r = _CACHE.get(s)
    if r is not None:
        return r
    r = _EXACT.get(s)
    if r is None:
        r = s
        if _FR_HINT.search(s) or any(fr in s for fr, _ in _FRAGS if len(fr) >= 7):
            r = _RX.sub(lambda m: _FMAP[m.group(0)], s)
    if len(_CACHE) < 50000:
        _CACHE[s] = r
    return r


# --------------------------------------------------------------------------
# Installation : interception des accesseurs Qt et traduction à l'affichage
# --------------------------------------------------------------------------
def install(app, lang: str):
    global LANG
    LANG = lang if lang in ("fr", "en") else "fr"
    if LANG == "fr":
        return
    from PySide6.QtCore import QEvent, QObject
    from PySide6 import QtWidgets as W
    from PySide6.QtWidgets import QMessageBox

    def wrap1(cls, name, idx=0):
        orig = getattr(cls, name)

        def f(self, *a, **k):
            a = list(a)
            if len(a) > idx and isinstance(a[idx], str):
                a[idx] = tr(a[idx])
            return orig(self, *a, **k)
        setattr(cls, name, f)

    for cls, name, idx in [(W.QLabel, "setText", 0), (W.QAbstractButton, "setText", 0),
                           (W.QWidget, "setToolTip", 0), (W.QWidget, "setWindowTitle", 0),
                           (W.QGroupBox, "setTitle", 0), (W.QLineEdit, "setPlaceholderText", 0),
                           (W.QComboBox, "addItem", 0), (W.QComboBox, "setItemText", 1),
                           (W.QTabWidget, "addTab", 1), (W.QTabWidget, "setTabText", 1),
                           (W.QStatusBar, "showMessage", 0), (W.QProgressDialog, "setLabelText", 0),
                           (W.QTableWidgetItem, "setText", 0), (W.QTreeWidgetItem, "setText", 1),
                           (W.QListWidgetItem, "setText", 0), (W.QMenu, "addAction", 0)]:
        try:
            wrap1(cls, name, idx)
        except Exception:
            pass

    orig_cb = W.QComboBox.addItems
    W.QComboBox.addItems = lambda self, items: orig_cb(self, [tr(x) for x in items])
    for cls in (W.QTableWidget, W.QTreeWidget):
        nm = "setHorizontalHeaderLabels" if cls is W.QTableWidget else "setHeaderLabels"
        o = getattr(cls, nm)
        setattr(cls, nm, (lambda o: lambda self, labels: o(self, [tr(x) for x in labels]))(o))

    for nm in ("information", "warning", "question", "critical"):
        o = getattr(QMessageBox, nm)

        def mk(o):
            def f(parent, title, text, *a, **k):
                return o(parent, tr(title), tr(text), *a, **k)
            return staticmethod(f)
        setattr(QMessageBox, nm, mk(o))
    for nm in ("getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory"):
        o = getattr(W.QFileDialog, nm)

        def mkf(o):
            def f(parent=None, caption="", *a, **k):
                a = list(a)
                if len(a) >= 2 and isinstance(a[1], str):
                    a[1] = tr(a[1])
                return o(parent, tr(caption), *a, **k)
            return staticmethod(f)
        setattr(W.QFileDialog, nm, mkf(o))
    o_txt = W.QInputDialog.getText

    def gt(parent, title, label, *a, **k):
        return o_txt(parent, tr(title), tr(label), *a, **k)
    W.QInputDialog.getText = staticmethod(gt)

    class Filter(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Polish and isinstance(obj, W.QWidget):
                translate_widget(obj)
            return False

    from PySide6.QtWidgets import QToolTip
    o_tip = QToolTip.showText

    def st(pos, text, *a, **k):
        return o_tip(pos, tr(text), *a, **k)
    QToolTip.showText = staticmethod(st)
    from . import theme as T
    for k, v in list(T.STATUS_LABEL.items()):
        T.STATUS_LABEL[k] = tr(v)
    app._i18n_filter = Filter(app)
    app.installEventFilter(app._i18n_filter)


def translate_widget(w):
    from PySide6 import QtWidgets as W
    try:
        if isinstance(w, (W.QLabel, W.QAbstractButton)):
            t = w.text()
            n = tr(t)
            if n != t:
                (W.QLabel.setText if isinstance(w, W.QLabel) else W.QAbstractButton.setText)(w, n)
        if isinstance(w, W.QGroupBox):
            w.setTitle(w.title())
        if isinstance(w, W.QLineEdit) and w.placeholderText():
            w.setPlaceholderText(w.placeholderText())
        if w.toolTip():
            w.setToolTip(w.toolTip())
        if w.isWindow() and w.windowTitle():
            w.setWindowTitle(w.windowTitle())
        if isinstance(w, W.QComboBox):
            for i in range(w.count()):
                t = w.itemText(i)
                n = tr(t)
                if n != t:
                    w.setItemText(i, n)
        if isinstance(w, W.QTabWidget):
            for i in range(w.count()):
                w.setTabText(i, w.tabText(i))
        if isinstance(w, W.QListWidget):
            for i in range(w.count()):
                it = w.item(i)
                it.setText(it.text())
        if isinstance(w, (W.QTableWidget,)):
            for c in range(w.columnCount()):
                h = w.horizontalHeaderItem(c)
                if h:
                    h.setText(h.text())
            for r in range(min(w.rowCount(), 300)):
                for c in range(w.columnCount()):
                    it = w.item(r, c)
                    if it and it.text():
                        it.setText(it.text())
        if isinstance(w, W.QTreeWidget):
            h = w.headerItem()
            for c in range(w.columnCount()):
                h.setText(c, h.text(c))
    except Exception:
        pass
