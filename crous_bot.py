import json
import os
import smtplib
import sys
import time
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURATION — via GitHub Secrets / variables d'environnement
# ==========================================
EMAIL_EXPEDITEUR = os.environ.get("EMAIL_EXPEDITEUR", "")
# Un mot de passe d'application Gmail est affiché avec des espaces : on les retire
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "").replace(" ", "")
EMAIL_DESTINATAIRE = os.environ.get("EMAIL_DESTINATAIRE", "")

# Telegram (optionnel) : alerte instantanée sur le téléphone
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# URL de ta zone. Si le Secret URL_CARTE_CROUS existe, il est utilisé en priorité.
# Sinon, on prend l'URL ci-dessous.
URL_PAR_DEFAUT = (
    "https://trouverunlogement.lescrous.fr/tools/47/search"
    "?bounds=1.7140057557361257_51.1052465308885_2.481675433470501_50.66251996729595"
)
URL_CARTE_CROUS = os.environ.get("URL_CARTE_CROUS", "").strip() or URL_PAR_DEFAUT
URL_BASE = "https://trouverunlogement.lescrous.fr"

FICHIER_MEMOIRE = "annonces_vues.json"

# Le script tourne en boucle pendant DUREE_TOTALE secondes, avec une vérification
# toutes les INTERVALLE secondes (le workflow le relance toutes les 5 minutes).
DUREE_TOTALE = int(os.environ.get("DUREE_SECONDES", "270"))
INTERVALLE = int(os.environ.get("INTERVALLE_SECONDES", "30"))

NB_TENTATIVES = 2           # essais par vérification si le site ne répond pas
PAUSE_ENTRE_TENTATIVES = 3  # secondes

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
# NOTIFICATIONS (mail + Telegram)
# ==========================================
def email_configure():
    return bool(EMAIL_EXPEDITEUR and EMAIL_PASSWORD and EMAIL_DESTINATAIRE)


def telegram_configure():
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def construire_sujet(nb):
    if nb == 1:
        return "🚨 CROUS : 1 logement disponible !"
    return f"🚨 CROUS : {nb} logements disponibles !"


def envoyer_email(nouvelles):
    """Envoie UN seul mail listant tous les nouveaux logements. Renvoie True si envoyé."""
    nb = len(nouvelles)

    lignes = ["Ça bouge sur ta zone CROUS !\n"]
    for lien, titre in nouvelles.items():
        lignes.append(f"🏠 {titre}\n🔗 {lien}\n")
    lignes.append("Connecte-toi vite sur le CROUS pour réserver !")

    msg = MIMEText("\n".join(lignes), "plain", "utf-8")
    msg["Subject"] = construire_sujet(nb)
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


def envoyer_telegram(nouvelles):
    """Envoie UN seul message Telegram listant les nouveaux logements. Renvoie True si envoyé."""
    nb = len(nouvelles)

    lignes = [construire_sujet(nb), ""]
    for lien, titre in nouvelles.items():
        lignes.append(f"🏠 {titre}\n🔗 {lien}\n")
    texte = "\n".join(lignes)
    if len(texte) > 4000:  # limite Telegram : 4096 caractères
        texte = texte[:3990] + "\n[...]"

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": texte},
            timeout=15,
        )
        if response.status_code == 200 and response.json().get("ok"):
            print(f"📱 Telegram envoyé ({nb} logement(s)).")
            return True
        # On n'affiche jamais l'URL (elle contient le token) : seulement la réponse de Telegram
        print(f"❌ Erreur Telegram {response.status_code} : {response.text[:200]}")
    except Exception as e:
        print(f"❌ Erreur Telegram : {type(e).__name__}")
    return False


def notifier(nouvelles):
    """Envoie sur tous les canaux configurés.
    Renvoie (au_moins_un_ok, tous_ok)."""
    resultats = []
    if telegram_configure():
        resultats.append(envoyer_telegram(nouvelles))
    if email_configure():
        resultats.append(envoyer_email(nouvelles))
    return any(resultats), all(resultats)


# ==========================================
# RÉCUPÉRATION DES ANNONCES
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


def recuperer_annonces():
    """Renvoie {lien: titre}, ou None si la vérification a échoué."""
    html = telecharger_page()
    if html is None:
        print("❌ Impossible de charger la page CROUS (bloqué ou site en panne ?).")
        return None

    annonces = extraire_annonces(html)

    # 0 annonce : soit il n'y a vraiment rien, soit le site a changé et le bot est aveugle.
    if not annonces and not page_indique_aucun_resultat(html):
        print("❌ Aucune annonce trouvée ET pas de message 'aucun logement' : "
              "le site a probablement changé de structure.")
        return None

    return annonces


# ==========================================
# PROGRAMME PRINCIPAL
# ==========================================
def main():
    if not (email_configure() or telegram_configure()):
        print("❌ Aucun canal d'alerte configuré : il faut les Secrets du mail "
              "(EMAIL_EXPEDITEUR / EMAIL_PASSWORD / EMAIL_DESTINATAIRE) "
              "et/ou ceux de Telegram (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).")
        return 1
    if not email_configure():
        print("ℹ️ Mail non configuré : alertes Telegram uniquement.")
    if not telegram_configure():
        print("ℹ️ Telegram non configuré : alertes par mail uniquement.")

    vues = charger_annonces_vues()
    debut = time.monotonic()
    nb_ok = 0
    nb_echecs = 0
    notif_ko = False      # aucun canal n'a fonctionné : on n'insiste plus pendant ce lancement
    canal_ko = False      # au moins un canal a échoué : le lancement finira en rouge
    tour = 0

    while True:
        tour += 1
        print(f"🔍 Vérification n°{tour}...")

        annonces = recuperer_annonces()

        if annonces is None:
            nb_echecs += 1
        else:
            nb_ok += 1
            print(f"📊 {len(annonces)} annonce(s) visible(s) actuellement.")
            nouvelles = {l: t for l, t in annonces.items() if l not in vues}

            if nouvelles and not notif_ko:
                for titre in nouvelles.values():
                    print(f"✨ NOUVEAU : {titre}")
                au_moins_un, tous = notifier(nouvelles)
                if not tous:
                    canal_ko = True
                if au_moins_un:
                    vues = set(annonces)
                else:
                    # Aucune alerte envoyée : on ne mémorise pas les nouvelles annonces
                    # (nouvel essai au prochain lancement) et on n'insiste pas ici.
                    notif_ko = True
                    vues = vues & set(annonces)
            elif nouvelles:
                vues = vues & set(annonces)
            else:
                # Mémoire = uniquement ce qui est visible MAINTENANT :
                # une annonce qui disparaît puis revient sera de nouveau notifiée.
                vues = set(annonces)

            sauvegarder_annonces_vues(vues)

        # Prochaine vérification, ou fin si le temps imparti est écoulé
        ecoule = time.monotonic() - debut
        if ecoule + INTERVALLE > DUREE_TOTALE:
            break
        time.sleep(INTERVALLE)

    print(f"🏁 Fin : {nb_ok} vérification(s) réussie(s), {nb_echecs} échec(s).")

    if notif_ko or canal_ko:
        return 1
    if nb_ok == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
