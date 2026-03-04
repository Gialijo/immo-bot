import os
import json
import logging
import tempfile
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from openai import OpenAI

# --- Configuration ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")

# Client OpenAI pour la transcription ET l'extraction IA
openai_client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# On garde en mémoire les infos collectées pour chaque conversation
conversations = {}

# Les 40 champs qu'on veut remplir pour chaque bien
CHAMPS_BIEN = {
    # Informations générales
    "type_bien": None,
    "type_transaction": None,
    "prix": None,
    "adresse": None,
    "code_postal": None,
    "ville": None,
    "etage": None,
    "nombre_etages_immeuble": None,

    # Surfaces
    "surface_habitable": None,
    "surface_terrain": None,
    "surface_sejour": None,
    "surface_cuisine": None,

    # Pièces
    "nombre_pieces": None,
    "nombre_chambres": None,
    "nombre_sdb": None,
    "nombre_wc": None,

    # Caractéristiques
    "balcon": None,
    "terrasse": None,
    "jardin": None,
    "cave": None,
    "parking": None,
    "garage": None,
    "piscine": None,
    "ascenseur": None,
    "digicode": None,
    "interphone": None,

    # État et énergie
    "etat_general": None,
    "annee_construction": None,
    "dpe_classe": None,
    "dpe_valeur": None,
    "ges_classe": None,
    "ges_valeur": None,
    "type_chauffage": None,
    "energie_chauffage": None,

    # Charges et copropriété
    "charges_copro_mois": None,
    "taxe_fonciere_an": None,
    "nombre_lots_copro": None,
    "syndic": None,

    # Informations vendeur
    "nom_proprietaire": None,
    "tel_proprietaire": None,
    "email_proprietaire": None,

    # Notes
    "points_forts": None,
    "points_faibles": None,
    "notes_agent": None,
}

# Le prompt système pour l'IA
PROMPT_EXTRACTION = """Tu es un assistant spécialisé en immobilier. Ton rôle est d'extraire les informations d'un bien immobilier à partir du message d'un agent immobilier.

L'agent te parle de manière naturelle, parfois informelle. Tu dois comprendre ce qu'il dit et extraire les informations correspondantes.

Voici les champs à remplir :

INFORMATIONS GÉNÉRALES :
- type_bien : Appartement, Maison, Studio, Loft, Local commercial, Terrain, Immeuble...
- type_transaction : Vente ou Location
- prix : en euros (nombre uniquement, ex: 280000)
- adresse : adresse de la rue
- code_postal : code postal (5 chiffres)
- ville : nom de la ville
- etage : numéro de l'étage (0 = RDC)
- nombre_etages_immeuble : nombre total d'étages de l'immeuble

SURFACES :
- surface_habitable : en m² (nombre uniquement)
- surface_terrain : en m² (nombre uniquement)
- surface_sejour : en m² (nombre uniquement)
- surface_cuisine : en m² (nombre uniquement)

PIÈCES :
- nombre_pieces : nombre total de pièces
- nombre_chambres : nombre de chambres
- nombre_sdb : nombre de salles de bain / salles d'eau
- nombre_wc : nombre de WC / toilettes

CARACTÉRISTIQUES (répondre Oui ou Non) :
- balcon, terrasse, jardin, cave, parking, garage, piscine, ascenseur, digicode, interphone

ÉTAT ET ÉNERGIE :
- etat_general : Neuf, Très bon, Bon, À rafraîchir, À rénover
- annee_construction : année (ex: 1975)
- dpe_classe : lettre de A à G
- dpe_valeur : valeur numérique du DPE
- ges_classe : lettre de A à G
- ges_valeur : valeur numérique du GES
- type_chauffage : Individuel ou Collectif
- energie_chauffage : Gaz, Électrique, Fioul, Bois, Pompe à chaleur, Mixte...

CHARGES ET COPROPRIÉTÉ :
- charges_copro_mois : en euros/mois (nombre uniquement)
- taxe_fonciere_an : en euros/an (nombre uniquement)
- nombre_lots_copro : nombre de lots dans la copropriété
- syndic : nom du syndic

INFORMATIONS VENDEUR :
- nom_proprietaire : nom du propriétaire
- tel_proprietaire : numéro de téléphone
- email_proprietaire : adresse email

NOTES :
- points_forts : les atouts du bien (texte libre)
- points_faibles : les défauts du bien (texte libre)
- notes_agent : observations personnelles de l'agent (texte libre)

RÈGLES IMPORTANTES :
1. Extrais UNIQUEMENT les informations clairement mentionnées dans le message.
2. Si une info n'est pas mentionnée, NE L'INCLUS PAS dans ta réponse.
3. Pour "T3", "T4" etc., déduis : T3 = 3 pièces, type_bien = Appartement.
4. Pour les prix : "280k" = 280000, "1.2M" = 1200000.
5. Si l'agent dit "pas d'ascenseur", mets ascenseur = "Non".
6. Si l'agent mentionne un point positif ("belle vue", "lumineux"), ajoute-le dans points_forts.
7. Si l'agent mentionne un défaut ("bruyant", "à refaire"), ajoute-le dans points_faibles.

Réponds UNIQUEMENT avec un objet JSON contenant les champs extraits. Pas de texte avant ou après.
Exemple de réponse :
{"type_bien": "Appartement", "nombre_pieces": 3, "surface_habitable": 65, "ville": "Lyon", "prix": 280000}
"""

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# --- Fonctions utilitaires ---

async def transcrire_audio(file_path: str) -> str:
    """Transcrit un fichier audio en texte avec Whisper"""
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
    """Utilise l'IA pour extraire les champs du message"""
    if not openai_client:
        return {}

    try:
        # On envoie aussi la fiche actuelle pour le contexte
        champs_deja_remplis = {k: v for k, v in fiche_actuelle.items() if v is not None}
        contexte = ""
        if champs_deja_remplis:
            contexte = f"\n\nChamps déjà remplis (pour contexte, ne pas répéter) :\n{json.dumps(champs_deja_remplis, ensure_ascii=False)}"

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": PROMPT_EXTRACTION},
                {"role": "user", "content": f"Message de l'agent : \"{message}\"{contexte}"}
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        resultat = response.choices[0].message.content
        champs_extraits = json.loads(resultat)

        # Nettoyer : ne garder que les champs valides
        champs_valides = {}
        for champ, valeur in champs_extraits.items():
            if champ in CHAMPS_BIEN and valeur is not None and valeur != "":
                champs_valides[champ] = valeur

        return champs_valides

    except Exception as e:
        logger.error(f"Erreur extraction IA: {e}")
        return {}


def formater_nouveaux_champs(champs: dict) -> str:
    """Formate les champs nouvellement extraits pour l'affichage"""
    if not champs:
        return "🤔 Je n'ai pas trouvé de nouvelles infos dans ton message."

    lignes = ["🧠 *Infos extraites :*\n"]
    for champ, valeur in champs.items():
        label = champ.replace("_", " ").capitalize()
        lignes.append(f"  ✅ {label} → {valeur}")

    return "\n".join(lignes)


async def traiter_texte(user_id: int, texte: str) -> str:
    """Traite un texte (écrit ou transcrit) : extraction IA + mise à jour fiche"""
    if user_id not in conversations:
        conversations[user_id] = json.loads(json.dumps(CHAMPS_BIEN))

    fiche = conversations[user_id]

    # Extraction IA
    nouveaux_champs = await extraire_champs(texte, fiche)

    # Mettre à jour la fiche
    for champ, valeur in nouveaux_champs.items():
        # Pour les notes (points_forts, points_faibles, notes_agent),
        # on accumule au lieu de remplacer
        if champ in ["points_forts", "points_faibles", "notes_agent"]:
            if fiche[champ] is not None:
                fiche[champ] = fiche[champ] + " | " + str(valeur)
            else:
                fiche[champ] = str(valeur)
        else:
            fiche[champ] = valeur

    # Compter la progression
    remplis = sum(1 for v in fiche.values() if v is not None)
    total = len(fiche)

    # Construire la réponse
    reponse = formater_nouveaux_champs(nouveaux_champs)
    reponse += f"\n\n📋 Fiche : {remplis}/{total} champs remplis"

    # Suggestions de champs manquants importants
    champs_prioritaires = {
        "type_bien": "Type de bien",
        "prix": "Prix",
        "surface_habitable": "Surface",
        "ville": "Ville",
        "nombre_pieces": "Nombre de pièces",
        "dpe_classe": "DPE",
    }
    manquants_importants = [
        label for champ, label in champs_prioritaires.items()
        if fiche.get(champ) is None
    ]

    if manquants_importants and remplis > 0:
        reponse += "\n\n💡 _Il me manque encore : " + ", ".join(manquants_importants) + "_"

    return reponse


# --- Commandes du bot ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quand l'utilisateur tape /start"""
    user_id = update.effective_user.id
    conversations[user_id] = json.loads(json.dumps(CHAMPS_BIEN))

    await update.message.reply_text(
        "👋 Salut ! Je suis ton assistant immobilier.\n\n"
        "Envoie-moi les infos du bien que tu visites, comme si tu parlais à un collègue.\n\n"
        "Tu peux m'envoyer :\n"
        "💬 Des messages écrits\n"
        "🎤 Des notes vocales\n\n"
        "Par exemple :\n"
        "« C'est un T3 de 65m² au 2ème étage, rue de la Paix à Lyon. "
        "Prix vendeur 280k. Bon état, DPE D. "
        "Balcon, cave. Charges 150€/mois. »\n\n"
        "🧠 Je comprends ce que tu dis et je remplis la fiche automatiquement !\n\n"
        "📋 /fiche → voir la fiche en cours\n"
        "❓ /manque → voir les champs à remplir\n"
        "🗑️ /reset → recommencer une nouvelle fiche"
    )


async def voir_fiche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quand l'utilisateur tape /fiche — affiche les champs remplis"""
    user_id = update.effective_user.id
    fiche = conversations.get(user_id, {})

    if not fiche or all(v is None for v in fiche.values()):
        await update.message.reply_text(
            "📋 La fiche est vide pour l'instant.\n"
            "Envoie-moi des infos sur le bien !"
        )
        return

    lignes = ["📋 *FICHE DU BIEN EN COURS*\n"]
    remplis = 0
    total = len(fiche)

    categories = {
        "🏠 Général": ["type_bien", "type_transaction", "prix", "adresse", "code_postal", "ville", "etage", "nombre_etages_immeuble"],
        "📐 Surfaces": ["surface_habitable", "surface_terrain", "surface_sejour", "surface_cuisine"],
        "🚪 Pièces": ["nombre_pieces", "nombre_chambres", "nombre_sdb", "nombre_wc"],
        "✨ Caractéristiques": ["balcon", "terrasse", "jardin", "cave", "parking", "garage", "piscine", "ascenseur", "digicode", "interphone"],
        "🔧 État & Énergie": ["etat_general", "annee_construction", "dpe_classe", "dpe_valeur", "ges_classe", "ges_valeur", "type_chauffage", "energie_chauffage"],
        "💰 Charges": ["charges_copro_mois", "taxe_fonciere_an", "nombre_lots_copro", "syndic"],
        "👤 Propriétaire": ["nom_proprietaire", "tel_proprietaire", "email_proprietaire"],
        "📝 Notes": ["points_forts", "points_faibles", "notes_agent"],
    }

    for cat_nom, champs in categories.items():
        cat_lignes = []
        for champ in champs:
            val = fiche.get(champ)
            if val is not None:
                label = champ.replace("_", " ").capitalize()
                cat_lignes.append(f"  ✅ {label}: {val}")
                remplis += 1
        if cat_lignes:
            lignes.append(f"\n{cat_nom}")
            lignes.extend(cat_lignes)

    lignes.insert(1, f"Progression: {remplis}/{total} champs remplis\n")

    await update.message.reply_text("\n".join(lignes), parse_mode="Markdown")


async def voir_manque(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quand l'utilisateur tape /manque — affiche les champs vides"""
    user_id = update.effective_user.id
    fiche = conversations.get(user_id, {})

    manquants = [
        champ.replace("_", " ").capitalize()
        for champ, val in fiche.items()
        if val is None
    ]

    if not manquants:
        await update.message.reply_text("🎉 Bravo ! Tous les champs sont remplis !")
    else:
        txt = "❓ *Champs encore vides :*\n\n"
        txt += "\n".join(f"  • {m}" for m in manquants)
        txt += f"\n\n_({len(manquants)} champs restants)_"
        await update.message.reply_text(txt, parse_mode="Markdown")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quand l'utilisateur tape /reset — remet la fiche à zéro"""
    user_id = update.effective_user.id
    conversations[user_id] = json.loads(json.dumps(CHAMPS_BIEN))
    await update.message.reply_text(
        "🗑️ Fiche remise à zéro !\n"
        "Tu peux commencer à me décrire un nouveau bien."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reçoit tous les messages texte et les analyse avec l'IA"""
    user_id = update.effective_user.id
    texte = update.message.text

    # Envoyer un message "en cours d'analyse"
    processing_msg = await update.message.reply_text("🧠 J'analyse ton message...")

    # Traiter le texte avec l'IA
    reponse = await traiter_texte(user_id, texte)

    await processing_msg.edit_text(reponse, parse_mode="Markdown")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reçoit les notes vocales, les transcrit, puis les analyse"""
    user_id = update.effective_user.id

    if user_id not in conversations:
        conversations[user_id] = json.loads(json.dumps(CHAMPS_BIEN))

    # Étape 1 : Transcrire
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

        # Étape 2 : Analyser avec l'IA
        await processing_msg.edit_text(
            f"🎤 Transcription : « {texte} »\n\n🧠 J'analyse les infos..."
        )

        reponse = await traiter_texte(user_id, texte)

        duree = voice.duration
        message_final = (
            f"🎤 *Note vocale* ({duree}s) :\n"
            f"« {texte} »\n\n"
            f"{reponse}"
        )

        await processing_msg.edit_text(message_final, parse_mode="Markdown")

        logger.info(f"Vocal traité ({duree}s): {texte[:100]}")

    except Exception as e:
        logger.error(f"Erreur traitement vocal: {e}")
        await processing_msg.edit_text(
            f"❌ Erreur lors du traitement de la note vocale.\n"
            f"Détail : {e}"
        )


# --- Démarrage du bot ---

def main():
    if not TOKEN:
        print("❌ ERREUR: La variable TELEGRAM_BOT_TOKEN n'est pas définie !")
        return

    if not OPENAI_KEY:
        print("⚠️ ATTENTION: La variable OPENAI_API_KEY n'est pas définie !")
        print("   Les notes vocales et l'extraction IA ne fonctionneront pas.")

    print("🚀 Démarrage du bot avec IA activée...")

    app = Application.builder().token(TOKEN).build()

    # Commandes
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fiche", voir_fiche))
    app.add_handler(CommandHandler("manque", voir_manque))
    app.add_handler(CommandHandler("reset", reset))

    # Messages texte
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Notes vocales
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Lancer le bot
    print("✅ Bot prêt ! IA active, en attente de messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
