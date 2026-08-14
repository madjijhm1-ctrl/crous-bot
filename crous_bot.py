import json
import os
import smtplib
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURATION — via variables d'environnement GitHub Secrets
# ==========================================
EMAIL_EXPEDITEUR = os.environ.get("EMAIL_EXPEDITEUR", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_DESTINATAIRE = os.environ.get("EMAIL_DESTINATAIRE", "")

URL_CARTE_CROUS = "https://trouverunlogement.lescrous.fr/tools/47/search?bounds=1.7140057557361257_51.1052465308885_2.481675433470501_50.66251996729595"

FICHIER_MEMOIRE = "annonces_vues.json"


def charger_annonces_vues():
    if os.path.exists(FICHIER_MEMOIRE):
        try:
            with open(FICHIER_MEMOIRE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            print(f"⚠️ Erreur lecture mémoire : {e}")
            return set()
    return set()


def sauvegarder_annonces_vues(annonces):
    try:
        with open(FICHIER_MEMOIRE, "w", encoding="utf-8") as f:
            json.dump(list(annonces), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Erreur sauvegarde mémoire : {e}")


def envoyer_email(titre, lien):
    sujet = "🚨 CROUS : Nouveau logement disponible !"
    corps = (
        f"Un nouveau logement a été repéré sur ta zone !\n\n"
        f"🏠 Logement : {titre}\n"
        f"🔗 Lien : {lien}\n\n"
        f"Connecte-toi vite sur le CROUS pour réserver !"
    )
    msg = MIMEText(corps, "plain", "utf-8")
    msg["Subject"] = sujet
    msg["From"] = EMAIL_EXPEDITEUR
    msg["To"] = EMAIL_DESTINATAIRE

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_EXPEDITEUR, EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"📧 Mail envoyé : {titre}")
    except Exception as e:
        print(f"❌ Erreur envoi mail : {e}")


def verifier_crous():
    print("🔍 Vérification CROUS en cours...")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
    }

    annonces_vues = charger_annonces_vues()

    try:
        response = requests.get(URL_CARTE_CROUS, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"⚠️ Erreur HTTP : {response.status_code}")
            return

        soup = BeautifulSoup(response.text, "html.parser")
        cards = (
            soup.select(".fr-card")
            or soup.find_all("article")
            or soup.select(".sret-card")
        )

        print(f"📊 {len(cards)} annonce(s) trouvée(s) sur la carte.")
        nouvelles = 0

        for card in cards:
            tag_a = card.find("a", href=True)
            if not tag_a:
                continue

            lien_relatif = tag_a["href"]
            lien_complet = (
                lien_relatif
                if lien_relatif.startswith("http")
                else f"https://trouverunlogement.lescrous.fr{lien_relatif}"
            )

            tag_titre = card.find(["h3", "h2", "a", "p"])
            titre = tag_titre.get_text(strip=True) if tag_titre else "Logement CROUS"

            if lien_complet not in annonces_vues:
                print(f"✨ NOUVEAU : {titre}")
                annonces_vues.add(lien_complet)
                envoyer_email(titre, lien_complet)
                nouvelles += 1

        sauvegarder_annonces_vues(annonces_vues)

        if nouvelles == 0:
            print("ℹ️ Aucune nouvelle annonce.")
        else:
            print(f"✅ {nouvelles} nouvelle(s) annonce(s) détectée(s) et mail(s) envoyé(s).")

    except Exception as e:
        print(f"⚠️ Erreur : {e}")


if __name__ == "__main__":
    verifier_crous()
