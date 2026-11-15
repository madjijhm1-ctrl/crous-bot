import json
import os
import smtplib
import sys
import time
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURATION — via GitHub Secrets
# ==========================================
EMAIL_EXPEDITEUR = os.environ.get("EMAIL_EXPEDITEUR", "")
# Un mot de passe d'application Gmail est affiché avec des espaces : on les retire
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "").replace(" ", "")
EMAIL_DESTINATAIRE = os.environ.get("EMAIL_DESTINATAIRE", "")

URL_CARTE_CROUS = (
    "https://trouverunlogement.lescrous.fr/tools/47/search"
    "?bounds=1.7140057557361257_51.1052465308885_2.481675433470501_50.66251996729595"
)
URL_BASE = "https://trouverunlogement.lescrous.fr"

FICHIER_MEMOIRE = "annonces_vues.json"

NB_TENTATIVES = 3          # nombre d'essais si le site ne répond pas
PAUSE_ENTRE_TENTATIVES = 5  # secondes

# Phrases qui indiquent que la page est valide mais qu'il n'y a aucun logement.
# Si le CROUS affiche une autre phrase, ajoute-la ici.
TEXTES_AUCUN_RESULTAT = ("aucun logement", "0 logement")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
}


# ==========================================
# MÉMOIRE
# ==========================================
def charger_annonces_vues():
    if not os.path.exists(FICHIER_MEMOIRE):
        print("ℹ️ Pas de mémoire existante (premier lancement ou cache perdu).")
        return set()
    try:
        with open(FICHIER_MEMOIRE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception as e:
        print(f"⚠️ Erreur lecture mémoire : {e}")
        return set()


def sauvegarder_annonces_vues(annonces):
    # Écriture dans un fichier temporaire puis remplacement : évite un fichier à moitié écrit
    tmp = FICHIER_MEMOIRE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sorted(annonces), f, ensure_ascii=False, indent=2)
        os.replace(tmp, FICHIER_MEMOIRE)
    except Exception as e:
        print(f"⚠️ Erreur sauvegarde mémoire : {e}")


# ==========================================
# MAIL
# ==========================================
def envoyer_email(nouvelles):
    """Envoie UN seul mail listant tous les nouveaux logements. Renvoie True si envoyé."""
    nb = len(nouvelles)
    sujet = (
        "🚨 CROUS : 1 logement disponible !"
        if nb == 1
        else f"🚨 CROUS : {nb} logements disponibles !"
    )

    lignes = ["Ça bouge sur ta zone CROUS !\n"]
    for lien, titre in nouvelles.items():
        lignes.append(f"🏠 {titre}\n🔗 {lien}\n")
    lignes.append("Connecte-toi vite sur le CROUS pour réserver !")

    msg = MIMEText("\n".join(lignes), "plain", "utf-8")
    msg["Subject"] = sujet
    msg["From"] = EMAIL_EXPEDITEUR
    msg["To"] = EMAIL_DESTINATAIRE

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.starttls()
            server.login(EMAIL_EXPEDITEUR, EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"📧 Mail envoyé ({nb} logement(s)).")
        return True
    except Exception as e:
        print(f"❌ Erreur envoi mail : {e}")
        return False


# ==========================================
# RÉCUPÉRATION DE LA PAGE
# ==========================================
def telecharger_page():
    """Renvoie le HTML de la page, ou None si le site ne répond pas correctement."""
    for tentative in range(1, NB_TENTATIVES + 1):
        try:
            response = requests.get(URL_CARTE_CROUS, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                return response.text
            print(f"⚠️ Erreur HTTP {response.status_code} (essai {tentative}/{NB_TENTATIVES})")
        except requests.RequestException as e:
            print(f"⚠️ Erreur réseau : {e} (essai {tentative}/{NB_TENTATIVES})")

        if tentative < NB_TENTATIVES:
            time.sleep(PAUSE_ENTRE_TENTATIVES)
    return None


def extraire_annonces(html):
    """Renvoie un dictionnaire {lien: titre} des annonces visibles sur la page."""
    soup = BeautifulSoup(html, "html.parser")
    cards = (
        soup.select(".fr-card")
        or soup.find_all("article")
        or soup.select(".sret-card")
    )

    annonces = {}
    for card in cards:
        tag_a = card.find("a", href=True)
        if not tag_a:
            continue

        lien = tag_a["href"]
        if not lien.startswith("http"):
            lien = f"{URL_BASE}{lien}"

        tag_titre = card.find(["h3", "h2"]) or tag_a
        titre = tag_titre.get_text(strip=True) or "Logement CROUS"

        annonces[lien] = titre
    return annonces


def page_indique_aucun_resultat(html):
    texte = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()
    return any(phrase in texte for phrase in TEXTES_AUCUN_RESULTAT)


# ==========================================
# PROGRAMME PRINCIPAL
# ==========================================
def main():
    print("🔍 Vérification CROUS en cours...")

    if not (EMAIL_EXPEDITEUR and EMAIL_PASSWORD and EMAIL_DESTINATAIRE):
        print("❌ Secrets manquants (EMAIL_EXPEDITEUR / EMAIL_PASSWORD / EMAIL_DESTINATAIRE).")
        return 1

    html = telecharger_page()
    if html is None:
        print("❌ Impossible de charger la page CROUS (bloqué ou site en panne ?).")
        return 1

    annonces = extraire_annonces(html)
    print(f"📊 {len(annonces)} annonce(s) visible(s) actuellement.")

    # 0 annonce : soit il n'y a vraiment rien, soit le site a changé et le bot est aveugle.
    # On ne touche pas à la mémoire dans le doute, et on fait échouer le run.
    if not annonces and not page_indique_aucun_resultat(html):
        print("❌ Aucune annonce trouvée ET pas de message 'aucun logement' : "
              "le site a probablement changé de structure.")
        return 1

    vues = charger_annonces_vues()
    nouvelles = {lien: titre for lien, titre in annonces.items() if lien not in vues}

    mail_ok = True
    if nouvelles:
        for titre in nouvelles.values():
            print(f"✨ NOUVEAU : {titre}")
        mail_ok = envoyer_email(nouvelles)
    else:
        print("ℹ️ Aucune nouvelle annonce.")

    # Mémoire = uniquement ce qui est visible MAINTENANT :
    #  - une annonce qui disparaît puis revient sera de nouveau notifiée ;
    #  - si le mail a échoué, les nouvelles annonces ne sont pas mémorisées,
    #    donc le prochain run réessaiera de t'envoyer le mail.
    if mail_ok:
        memoire = set(annonces)
    else:
        memoire = vues & set(annonces)
    sauvegarder_annonces_vues(memoire)

    return 0 if mail_ok else 1


if __name__ == "__main__":
    sys.exit(main())
