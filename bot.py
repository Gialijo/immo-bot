import os
import json
import logging
import tempfile
import re
from copy import deepcopy
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from openai import OpenAI
from fpdf import FPDF


# --- Configuration ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")

openai_client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None
conversations = {}


# --- Modèle de fiche ---

CHAMPS_BIEN = {
    # Obligatoires
    "type_bien": None,                  # Appartement / Maison / Hôtel Particulier
    "adresse": None,
    "ville": None,
    "nom_proprietaire": None,          # ou nom société
    "etage": None,                     # sauf maison / hôtel particulier
    "surface": None,
    "nombre_pieces": None,
    "nombre_chambres": None,
    "etat_bien": None,
    "etat_parties_communes": None,
    "nombre_salles_bains": None,
    "nombre_salles_eau": None,
    "wc": None,
    "type_chauffage": None,
    "ascenseur": None,                 # sauf maison / hôtel particulier
    "dpe_lettre": None,
    "points_forts_appartement": None,
    "points_faibles_appartement": None,

    # Secondaires
    "prix": None,
    "charges_mois": None,
    "taxe_fonciere": None,
    "libre_ou_occupe": None,
    "cave": None,
    "parking": None,
    "balcon": None,
    "surface_balcon": None,
    "terrasse": None,
    "surface_terrasse": None,
    "jardin": None,
    "surface_jardin": None,
    "nombre_etages_immeuble": None,
    "annee_construction_immeuble": None,
    "standing_immeuble": None,
    "type_cuisine": None,
    "climatisation": None,
    "type_fenetre": None,
    "vue": None,
    "exposition": None,
    "hauteur_sous_plafond": None,
    "piscine": None,
    "annexe": None,
    "copropriete": None,
    "georisques": None,
    "nom_syndic": None,
    "code_immeuble": None,
    "digicode": None,
    "interphone": None,
    "nombre_lots_copro": None,
    "email_proprietaire": None,
    "tel_proprietaire": None,
}

LIBELLES = {
    "type_bien": "Type de bien",
    "adresse": "Adresse",
    "ville": "Ville",
    "nom_proprietaire": "Nom propriétaire / société",
    "etage": "Étage",
    "surface": "Surface",
    "nombre_pieces": "Nombre de pièces",
    "nombre_chambres": "Nombre de chambres",
    "etat_bien": "État du bien",
    "etat_parties_communes": "État des parties communes",
    "nombre_salles_bains": "Nombre de salles de bains",
    "nombre_salles_eau": "Nombre de salles d'eau",
    "wc": "WC",
    "type_chauffage": "Type de chauffage",
    "ascenseur": "Ascenseur",
    "dpe_lettre": "Lettre DPE",
    "points_forts_appartement": "Points forts appartement",
    "points_faibles_appartement": "Points faibles appartement",
    "prix": "Prix",
    "charges_mois": "Charges / mois",
    "taxe_fonciere": "Taxe foncière",
    "libre_ou_occupe": "Libre ou occupé",
    "cave": "Cave",
    "parking": "Parking",
    "balcon": "Balcon",
    "surface_balcon": "Surface balcon",
    "terrasse": "Terrasse",
    "surface_terrasse": "Surface terrasse",
    "jardin": "Jardin",
    "surface_jardin": "Surface jardin",
    "nombre_etages_immeuble": "Nombre d'étages immeuble",
    "annee_construction_immeuble": "Année construction immeuble",
    "standing_immeuble": "Standing immeuble",
    "type_cuisine": "Type de cuisine",
    "climatisation": "Climatisation",
    "type_fenetre": "Type de fenêtre",
    "vue": "Vue",
    "exposition": "Exposition",
    "hauteur_sous_plafond": "Hauteur sous plafond",
    "piscine": "Piscine",
    "annexe": "Annexe",
    "copropriete": "Copropriété",
    "georisques": "Exposé à géorisques",
    "nom_syndic": "Nom du syndic",
    "code_immeuble": "Code immeuble",
    "digicode": "Digicode",
    "interphone": "Interphone",
    "nombre_lots_copro": "Nombre de lots de copro",
    "email_proprietaire": "Email propriétaire",
    "tel_proprietaire": "Téléphone propriétaire",
}

DPE_AUTORISES = ["A", "B", "C", "D", "E", "F", "NC"]


# --- Prompt IA ---

PROMPT_EXTRACTION = """
Tu es un assistant spécialisé en immobilier haut de gamme en France.
Tu reçois le message libre d'un agent immobilier qui décrit un bien.

Tu dois extraire UNIQUEMENT les informations clairement mentionnées dans le message,
et répondre UNIQUEMENT avec un objet JSON.

Ne mets jamais de texte avant ou après le JSON.

Champs à extraire :

OBLIGATOIRES
- type_bien : Appartement, Maison, Hôtel Particulier
- adresse
- ville
- nom_proprietaire : nom et prénom du propriétaire ou nom de la société
- etage : numéro d'étage, ou 0 pour rez-de-chaussée
- surface : surface en m² (nombre uniquement)
- nombre_pieces : nombre total de pièces
- nombre_chambres : nombre de chambres
- etat_bien : exactement parmi
  A rafraichir, A renover, Bon etat, En excellent etat, Gros travaux a prevoir, Parfait etat
- etat_parties_communes : exactement parmi
  A rafraichir, A renover, Bon etat, En excellent etat, Gros travaux a prevoir, Parfait etat
- nombre_salles_bains
- nombre_salles_eau
- wc
- type_chauffage
- ascenseur : Oui ou Non
- dpe_lettre : A, B, C, D, E, F, NC
- points_forts_appartement : texte libre
- points_faibles_appartement : texte libre

SECONDAIRES
- prix : nombre uniquement en euros
- charges_mois : nombre uniquement en euros
- taxe_fonciere : nombre uniquement en euros
- libre_ou_occupe : Libre ou Occupé
- cave : Oui ou Non
- parking : Oui ou Non
- balcon : Oui ou Non
- surface_balcon : nombre uniquement en m²
- terrasse : Oui ou Non
- surface_terrasse : nombre uniquement en m²
- jardin : Oui ou Non
- surface_jardin : nombre uniquement en m²
- nombre_etages_immeuble
- annee_construction_immeuble
- standing_immeuble
- type_cuisine
- climatisation : Oui ou Non
- type_fenetre
- vue
- exposition
- hauteur_sous_plafond
- piscine : Oui ou Non
- annexe
- copropriete : Oui ou Non
- georisques : Oui ou Non
- nom_syndic
- code_immeuble
- digicode : Oui ou Non
- interphone : Oui ou Non
- nombre_lots_copro
- email_proprietaire
- tel_proprietaire

Règles :
1. N'invente jamais.
2. Si une info n'est pas dite clairement, ne la mets pas.
3. Si l'agent dit "T3", "3 pieces", "trois pieces", alors nombre_pieces = 3.
4. Si l'agent dit "pas d'ascenseur", ascenseur = "Non".
5. Si l'agent dit "avec ascenseur", ascenseur = "Oui".
6. Si l'agent dit "DPE inconnu" ou pas encore fait, dpe_lettre = "NC".
7. Si le bien est décrit comme "hotel particulier" ou "hôtel particulier", type_bien = "Hôtel Particulier".
8. Réponds avec des nombres simples pour les surfaces, prix, charges, taxe foncière, etc.
9. Pour les booléens, utilise strictement "Oui" ou "Non".
10. Pour libre_ou_occupe, utilise strictement "Libre" ou "Occupé".
11. Si l'agent mentionne des atouts du bien, mets-les dans points_forts_appartement.
12. Si l'agent mentionne des défauts du bien, mets-les dans points_faibles_appartement.

Exemple de réponse :
{
  "type_bien": "Appartement",
  "ville": "Paris",
  "surface": 145,
  "nombre_pieces": 5,
  "ascenseur": "Oui",
  "dpe_lettre": "D"
}
"""


# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# --- Utilitaires ---

def nouvelle_fiche():
    return deepcopy(CHAMPS_BIEN)


def est_oui(valeur):
    return str(valeur).strip().lower() in ["oui", "true", "1", "yes"]


def est_non(valeur):
    return str(valeur).strip().lower() in ["non", "false", "0", "no"]


def normaliser_chaine(valeur):
    if valeur is None:
        return None
    return str(valeur).strip()


def normaliser_nombre(valeur):
    if valeur is None:
        return None

    if isinstance(valeur, (int, float)):
        return int(valeur) if float(valeur).is_integer() else float(valeur)

    texte = str(valeur).strip().lower()
    texte = texte.replace("€", "").replace("eur", "")
    texte = texte.replace(",", ".")
    texte = texte.replace("m²", "").replace("m2", "").strip()

    match = re.match(r"^(\d+(\.\d+)?)\s*k$", texte)
    if match:
        return int(float(match.group(1)) * 1000)

    match = re.match(r"^(\d+(\.\d+)?)\s*m$", texte)
    if match:
        return int(float(match.group(1)) * 1000000)

    try:
        num = float(texte)
        return int(num) if num.is_integer() else num
    except Exception:
        return valeur


def normaliser_bool_oui_non(valeur):
    if valeur is None:
        return None
    texte = str(valeur).strip().lower()
    if texte in ["oui", "yes", "true", "1", "avec"]:
        return "Oui"
    if texte in ["non", "no", "false", "0", "sans"]:
        return "Non"
    return str(valeur).strip()


def normaliser_type_bien(valeur):
    if not valeur:
        return None
    texte = str(valeur).strip().lower()
    if "hotel particulier" in texte or "hôtel particulier" in texte:
        return "Hôtel Particulier"
    if "maison" in texte:
        return "Maison"
    if "appartement" in texte or texte.startswith("t") or "studio" in texte:
        return "Appartement"
    return str(valeur).strip()


def normaliser_dpe(valeur):
    if valeur is None:
        return None
    texte = str(valeur).strip().upper()
    if texte in DPE_AUTORISES:
        return texte
    return str(valeur).strip().upper()


def normaliser_etat(valeur):
    if valeur is None:
        return None

    mapping = {
        "a rafraichir": "A rafraichir",
        "à rafraichir": "A rafraichir",
        "a renover": "A renover",
        "a rénover": "A renover",
        "à renover": "A renover",
        "à rénover": "A renover",
        "bon etat": "Bon etat",
        "bon état": "Bon etat",
        "en excellent etat": "En excellent etat",
        "en excellent état": "En excellent etat",
        "gros travaux a prevoir": "Gros travaux a prevoir",
        "gros travaux à prevoir": "Gros travaux a prevoir",
        "gros travaux a prévoir": "Gros travaux a prevoir",
        "gros travaux à prévoir": "Gros travaux a prevoir",
        "parfait etat": "Parfait etat",
        "parfait état": "Parfait etat",
    }

    texte = str(valeur).strip().lower()
    return mapping.get(texte, str(valeur).strip())


def normaliser_valeur(champ, valeur):
    if valeur is None or valeur == "":
        return None

    champs_numeriques = {
        "prix",
        "charges_mois",
        "taxe_fonciere",
        "surface",
        "surface_balcon",
        "surface_terrasse",
        "surface_jardin",
        "nombre_pieces",
        "nombre_chambres",
        "nombre_salles_bains",
        "nombre_salles_eau",
        "wc",
        "etage",
        "nombre_etages_immeuble",
        "annee_construction_immeuble",
        "nombre_lots_copro",
    }

    champs_oui_non = {
        "ascenseur", "cave", "parking", "balcon", "terrasse", "jardin",
        "climatisation", "piscine", "copropriete", "georisques",
        "digicode", "interphone"
    }

    if champ in champs_numeriques:
        return normaliser_nombre(valeur)
    if champ in champs_oui_non:
        return normaliser_bool_oui_non(valeur)
    if champ == "type_bien":
        return normaliser_type_bien(valeur)
    if champ == "dpe_lettre":
        return normaliser_dpe(valeur)
    if champ in {"etat_bien", "etat_parties_communes"}:
        return normaliser_etat(valeur)
    if champ == "libre_ou_occupe":
        texte = str(valeur).strip().lower()
        if texte == "libre":
            return "Libre"
        if texte in ["occupe", "occupé"]:
            return "Occupé"
        return str(valeur).strip()

    return normaliser_chaine(valeur)


def nettoyer_fiche(fiche: dict):
    type_bien = fiche.get("type_bien")

    if type_bien in ["Maison", "Hôtel Particulier"]:
        fiche["etage"] = None
        fiche["ascenseur"] = None

    if est_non(fiche.get("balcon")):
        fiche["surface_balcon"] = None

    if est_non(fiche.get("terrasse")):
        fiche["surface_terrasse"] = None

    if est_non(fiche.get("jardin")):
        fiche["surface_jardin"] = None

    if est_non(fiche.get("copropriete")):
        fiche["nom_syndic"] = None


def champs_obligatoires_actifs(fiche: dict):
    obligatoires = [
        "type_bien",
        "adresse",
        "ville",
        "nom_proprietaire",
        "surface",
        "nombre_pieces",
        "nombre_chambres",
        "etat_bien",
        "etat_parties_communes",
        "nombre_salles_bains",
        "nombre_salles_eau",
        "wc",
        "type_chauffage",
        "dpe_lettre",
        "points_forts_appartement",
        "points_faibles_appartement",
    ]

    if fiche.get("type_bien") not in ["Maison", "Hôtel Particulier"]:
        obligatoires.append("etage")
        obligatoires.append("ascenseur")

    return obligatoires


def champs_secondaires():
    return [
        "prix",
        "charges_mois",
        "taxe_fonciere",
        "libre_ou_occupe",
        "cave",
        "parking",
        "balcon",
        "surface_balcon",
        "terrasse",
        "surface_terrasse",
        "jardin",
        "surface_jardin",
        "nombre_etages_immeuble",
        "annee_construction_immeuble",
        "standing_immeuble",
        "type_cuisine",
        "climatisation",
        "type_fenetre",
        "vue",
        "exposition",
        "hauteur_sous_plafond",
        "piscine",
        "annexe",
        "copropriete",
        "georisques",
        "nom_syndic",
        "code_immeuble",
        "digicode",
        "interphone",
        "nombre_lots_copro",
        "email_proprietaire",
        "tel_proprietaire",
    ]


def champs_manquants_obligatoires(fiche: dict):
    return [c for c in champs_obligatoires_actifs(fiche) if fiche.get(c) in [None, ""]]


def champs_manquants_secondaires(fiche: dict):
    manquants = []
    for champ in champs_secondaires():
        if champ == "surface_balcon" and est_non(fiche.get("balcon")):
            continue
        if champ == "surface_terrasse" and est_non(fiche.get("terrasse")):
            continue
        if champ == "surface_jardin" and est_non(fiche.get("jardin")):
            continue
        if champ == "nom_syndic" and est_non(fiche.get("copropriete")):
            continue
        if fiche.get(champ) in [None, ""]:
            manquants.append(champ)
    return manquants


def formater_valeur_pdf(champ, valeur):
    if valeur is None:
        return None
    if champ in {"prix", "charges_mois", "taxe_fonciere"}:
        return f"{valeur} EUR"
    if champ in {"surface", "surface_balcon", "surface_terrasse", "surface_jardin", "hauteur_sous_plafond"}:
        return f"{valeur} m2"
    return str(valeur)


# --- IA / Audio ---

async def transcrire_audio(file_path: str) -> str:
    if not openai_client:
        return "❌ Erreur : clé OpenAI non configurée."
    try:
        with open(file_path, "rb") as audio_file:
            transcription = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="fr",
            )
        return transcription.text
    except Exception as e:
        logger.error(f"Erreur transcription: {e}")
        return f"❌ Erreur lors de la transcription : {e}"


async def extraire_champs(message: str, fiche_actuelle: dict) -> dict:
    if not openai_client:
        return {}

    try:
        champs_deja_remplis = {k: v for k, v in fiche_actuelle.items() if v is not None}
        contexte = ""
        if champs_deja_remplis:
            contexte = (
                "\n\nContexte de la fiche déjà remplie :\n"
                + json.dumps(champs_deja_remplis, ensure_ascii=False)
            )

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": PROMPT_EXTRACTION},
                {"role": "user", "content": f'Message de l’agent : "{message}"{contexte}'}
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        contenu = response.choices[0].message.content
        resultat = json.loads(contenu)

        champs_valides = {}
        for champ, valeur in resultat.items():
            if champ in CHAMPS_BIEN and valeur not in [None, ""]:
                champs_valides[champ] = normaliser_valeur(champ, valeur)

        return champs_valides

    except Exception as e:
        logger.error(f"Erreur extraction IA: {e}")
        return {}


def formater_nouveaux_champs(champs: dict) -> str:
    if not champs:
        return "🤔 Je n’ai pas trouvé de nouvelle info exploitable dans ton message."

    lignes = ["🧠 *Infos extraites :*\n"]
    for champ, valeur in champs.items():
        lignes.append(f"✅ {LIBELLES.get(champ, champ)} → {valeur}")
    return "\n".join(lignes)


async def traiter_texte(user_id: int, texte: str) -> str:
    if user_id not in conversations:
        conversations[user_id] = nouvelle_fiche()

    fiche = conversations[user_id]
    nouveaux_champs = await extraire_champs(texte, fiche)

    for champ, valeur in nouveaux_champs.items():
        fiche[champ] = valeur

    nettoyer_fiche(fiche)

    obligatoires = champs_obligatoires_actifs(fiche)
    nb_obligatoires_remplis = sum(1 for c in obligatoires if fiche.get(c) not in [None, ""])
    nb_obligatoires_total = len(obligatoires)

    nb_total_remplis = sum(1 for v in fiche.values() if v not in [None, ""])
    nb_total = len(fiche)

    reponse = formater_nouveaux_champs(nouveaux_champs)
    reponse += f"\n\n📌 Obligatoires : {nb_obligatoires_remplis}/{nb_obligatoires_total}"
    reponse += f"\n📋 Total fiche : {nb_total_remplis}/{nb_total}"

    manquants = champs_manquants_obligatoires(fiche)
    if manquants:
        reponse += "\n\n❗ *Il me manque encore ces champs obligatoires :*\n"
        for champ in manquants:
            reponse += f"\n• {LIBELLES.get(champ, champ)}"

        reponse += "\n\n✍️ Envoie-moi toutes ces infos d’un coup dans un seul message."
        reponse += "\n\n💡 Si tu veux, je peux aussi te lister les champs secondaires manquants avec la commande /manque"
    else:
        secondaires = champs_manquants_secondaires(fiche)
        if secondaires:
            reponse += "\n\n✅ Tous les champs obligatoires sont remplis."
            reponse += "\n💡 Si tu veux, je peux aussi te lister les champs secondaires manquants avec la commande /manque"
        else:
            reponse += "\n\n🎉 Tout est rempli."

    return reponse


# --- PDF ---

def generer_pdf(fiche: dict) -> str:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_fill_color(41, 65, 122)
    pdf.rect(0, 0, 210, 35, "F")

    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_y(8)
    pdf.cell(0, 10, "FICHE BIEN IMMOBILIER", align="C", ln=1)

    sous_titre = fiche.get("type_bien") or "Bien"
    if fiche.get("ville"):
        sous_titre += f" - {fiche.get('ville')}"
    if fiche.get("prix"):
        sous_titre += f" - {fiche.get('prix')} EUR"

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, sous_titre, align="C", ln=1)

    pdf.ln(12)

    def titre_section(titre):
        pdf.set_fill_color(230, 236, 245)
        pdf.set_text_color(41, 65, 122)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, f"  {titre}", ln=1, fill=True)
        pdf.ln(1)

    def ligne(label, valeur):
        if valeur is None or valeur == "":
            return
        pdf.set_text_color(80, 80, 80)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(65, 7, label)
        pdf.set_text_color(30, 30, 30)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 7, str(valeur))

    titre_section("OBLIGATOIRES")
    for champ in champs_obligatoires_actifs(fiche):
        ligne(LIBELLES.get(champ, champ), formater_valeur_pdf(champ, fiche.get(champ)))

    pdf.ln(3)
    titre_section("SECONDAIRES")
    for champ in champs_secondaires():
        if champ == "surface_balcon" and est_non(fiche.get("balcon")):
            continue
        if champ == "surface_terrasse" and est_non(fiche.get("terrasse")):
            continue
        if champ == "surface_jardin" and est_non(fiche.get("jardin")):
            continue
        if champ == "nom_syndic" and est_non(fiche.get("copropriete")):
            continue

        ligne(LIBELLES.get(champ, champ), formater_valeur_pdf(champ, fiche.get(champ)))

    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(140, 140, 140)
    date_str = datetime.now().strftime("%d/%m/%Y à %Hh%M")
    pdf.cell(0, 5, f"Fiche générée automatiquement le {date_str}", align="C")

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    pdf.output(tmp.name)
    return tmp.name


# --- Commandes ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = nouvelle_fiche()

    await update.message.reply_text(
        "👋 Salut ! Je suis ton assistant immobilier.\n\n"
        "Tu peux m’envoyer :\n"
        "💬 du texte\n"
        "🎤 des notes vocales\n\n"
        "Je remplis automatiquement la fiche du bien.\n\n"
        "Exemple :\n"
        "« Appartement avenue Victor Hugo à Paris 16, 4e étage avec ascenseur, "
        "145 m², 6 pièces, 3 chambres, bon état, parties communes en excellent état, "
        "2 salles de bains, 1 salle d’eau, 2 WC, chauffage collectif, DPE D. "
        "Points forts : vue, lumière, plan. Points faibles : cuisine à refaire. »\n\n"
        "Commandes :\n"
        "📋 /fiche → voir la fiche\n"
        "❓ /manque → voir ce qu’il manque\n"
        "📄 /export → générer le PDF\n"
        "🗑️ /reset → recommencer"
    )


async def voir_fiche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    fiche = conversations.get(user_id, nouvelle_fiche())

    if all(v in [None, ""] for v in fiche.values()):
        await update.message.reply_text("📋 La fiche est vide pour l’instant.")
        return

    lignes = ["📋 *FICHE EN COURS*\n"]

    obligatoires = champs_obligatoires_actifs(fiche)
    remplis_obligatoires = sum(1 for c in obligatoires if fiche.get(c) not in [None, ""])
    lignes.append(f"Obligatoires : {remplis_obligatoires}/{len(obligatoires)}\n")

    lignes.append("🏠 *Champs obligatoires*")
    for champ in obligatoires:
        valeur = fiche.get(champ)
        etat = "✅" if valeur not in [None, ""] else "⬜"
        lignes.append(f"{etat} {LIBELLES.get(champ, champ)} : {valeur if valeur not in [None, ''] else '—'}")

    lignes.append("\n✨ *Champs secondaires*")
    for champ in champs_secondaires():
        if champ == "surface_balcon" and est_non(fiche.get("balcon")):
            continue
        if champ == "surface_terrasse" and est_non(fiche.get("terrasse")):
            continue
        if champ == "surface_jardin" and est_non(fiche.get("jardin")):
            continue
        if champ == "nom_syndic" and est_non(fiche.get("copropriete")):
            continue

        valeur = fiche.get(champ)
        if valeur not in [None, ""]:
            lignes.append(f"✅ {LIBELLES.get(champ, champ)} : {valeur}")

    await update.message.reply_text("\n".join(lignes), parse_mode="Markdown")


async def voir_manque(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    fiche = conversations.get(user_id, nouvelle_fiche())

    manquants_obligatoires = champs_manquants_obligatoires(fiche)
    manquants_secondaires = champs_manquants_secondaires(fiche)

    if not manquants_obligatoires and not manquants_secondaires:
        await update.message.reply_text("🎉 Tout est rempli.")
        return

    txt = "❓ *Champs manquants*\n\n"

    if manquants_obligatoires:
        txt += "*Obligatoires :*\n"
        txt += "\n".join(f"• {LIBELLES.get(c, c)}" for c in manquants_obligatoires)
        txt += "\n\n"
    else:
        txt += "✅ Tous les champs obligatoires sont remplis.\n\n"

    if manquants_secondaires:
        txt += "*Secondaires :*\n"
        txt += "\n".join(f"• {LIBELLES.get(c, c)}" for c in manquants_secondaires[:20])
        if len(manquants_secondaires) > 20:
            txt += f"\n… et {len(manquants_secondaires) - 20} autres"

    await update.message.reply_text(txt, parse_mode="Markdown")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = nouvelle_fiche()
    await update.message.reply_text("🗑️ Fiche remise à zéro.")


async def export_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    fiche = conversations.get(user_id, nouvelle_fiche())

    if all(v in [None, ""] for v in fiche.values()):
        await update.message.reply_text("📋 La fiche est vide.")
        return

    processing_msg = await update.message.reply_text("📄 Je génère le PDF...")

    try:
        pdf_path = generer_pdf(fiche)

        nom_fichier = "Fiche_Bien"
        if fiche.get("type_bien"):
            nom_fichier += f"_{fiche['type_bien']}"
        if fiche.get("ville"):
            nom_fichier += f"_{fiche['ville']}"
        nom_fichier += "_" + datetime.now().strftime("%d%m%Y") + ".pdf"
        nom_fichier = nom_fichier.replace(" ", "_")

        with open(pdf_path, "rb") as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                filename=nom_fichier,
                caption="📄 Voici la fiche du bien."
            )

        os.unlink(pdf_path)
        await processing_msg.delete()

    except Exception as e:
        logger.error(f"Erreur génération PDF: {e}")
        await processing_msg.edit_text(f"❌ Erreur lors de la génération du PDF : {e}")


# --- Messages ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    texte = update.message.text

    processing_msg = await update.message.reply_text("🧠 J’analyse ton message...")
    reponse = await traiter_texte(user_id, texte)
    await processing_msg.edit_text(reponse, parse_mode="Markdown")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in conversations:
        conversations[user_id] = nouvelle_fiche()

    processing_msg = await update.message.reply_text("🎤 Je transcris ta note vocale...")

    try:
        voice = update.message.voice
        voice_file = await context.bot.get_file(voice.file_id)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await voice_file.download_to_drive(tmp.name)
            tmp_path = tmp.name

        texte = await transcrire_audio(tmp_path)
        os.unlink(tmp_path)

        if texte.startswith("❌"):
            await processing_msg.edit_text(texte)
            return

        await processing_msg.edit_text(
            f"🎤 Transcription : « {texte} »\n\n🧠 J’analyse les infos..."
        )

        reponse = await traiter_texte(user_id, texte)

        message_final = (
            f"🎤 *Note vocale* ({voice.duration}s)\n"
            f"« {texte} »\n\n"
            f"{reponse}"
        )
        await processing_msg.edit_text(message_final, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Erreur traitement vocal: {e}")
        await processing_msg.edit_text(
            f"❌ Erreur lors du traitement de la note vocale : {e}"
        )


# --- Main ---

def main():
    if not TOKEN:
        print("❌ ERREUR : TELEGRAM_BOT_TOKEN n'est pas défini.")
        return

    if not OPENAI_KEY:
        print("⚠️ ATTENTION : OPENAI_API_KEY n'est pas défini.")

    print("🚀 Démarrage du bot immobilier...")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fiche", voir_fiche))
    app.add_handler(CommandHandler("manque", voir_manque))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("export", export_pdf))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("✅ Bot prêt.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
