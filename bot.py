import os
import json
import logging
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Configuration ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# On garde en mémoire les infos collectées pour chaque conversation
conversations = {}

# Les 40 champs qu'on veut remplir pour chaque bien
CHAMPS_BIEN = {
    # Informations générales
    "type_bien": None,           # Appartement, Maison, Local commercial...
    "type_transaction": None,    # Vente, Location
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
    "etat_general": None,        # Neuf, Bon, À rafraîchir, À rénover
    "annee_construction": None,
    "dpe_classe": None,          # A, B, C, D, E, F, G
    "dpe_valeur": None,
    "ges_classe": None,
    "ges_valeur": None,
    "type_chauffage": None,      # Individuel, Collectif
    "energie_chauffage": None,   # Gaz, Électrique, Fioul, Bois...

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

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# --- Commandes du bot ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quand l'utilisateur tape /start"""
    user_id = update.effective_user.id
    conversations[user_id] = json.loads(json.dumps(CHAMPS_BIEN))

    await update.message.reply_text(
        "👋 Salut ! Je suis ton assistant immobilier.\n\n"
        "Envoie-moi les infos du bien que tu visites, comme si tu parlais à un collègue. "
        "Par exemple :\n\n"
        "💬 « C'est un T3 de 65m² au 2ème étage, rue de la Paix à Lyon. "
        "Prix vendeur 280k. Bon état général, DPE D. "
        "Il y a un balcon et une cave. Charges 150€/mois. »\n\n"
        "Tu peux m'envoyer les infos en plusieurs messages, petit à petit.\n\n"
        "📋 Tape /fiche pour voir la fiche en cours\n"
        "🗑️ Tape /reset pour recommencer une nouvelle fiche\n"
        "❓ Tape /manque pour voir les champs qu'il reste à remplir"
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

    # Construire le résumé des champs remplis
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
    """Reçoit tous les messages texte de l'utilisateur"""
    user_id = update.effective_user.id
    texte = update.message.text

    # Créer une fiche si elle n'existe pas encore
    if user_id not in conversations:
        conversations[user_id] = json.loads(json.dumps(CHAMPS_BIEN))

    # Pour l'instant, on confirme la réception
    # (Dans la Brique 4, c'est ici que l'IA analysera le message)
    fiche = conversations[user_id]
    remplis = sum(1 for v in fiche.values() if v is not None)
    total = len(fiche)

    await update.message.reply_text(
        f"✅ Bien noté ! J'ai enregistré ton message.\n\n"
        f"📋 Fiche : {remplis}/{total} champs remplis\n\n"
        f"💡 _Dans la prochaine version, je comprendrai automatiquement "
        f"les infos et remplirai la fiche tout seul !_\n\n"
        f"Ton message : « {texte[:100]}{'...' if len(texte) > 100 else ''} »",
        parse_mode="Markdown",
    )


# --- Démarrage du bot ---

def main():
    if not TOKEN:
        print("❌ ERREUR: La variable TELEGRAM_BOT_TOKEN n'est pas définie !")
        print("   Ajoute-la dans les variables d'environnement de Railway.")
        return

    print("🚀 Démarrage du bot...")

    app = Application.builder().token(TOKEN).build()

    # Commandes
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fiche", voir_fiche))
    app.add_handler(CommandHandler("manque", voir_manque))
    app.add_handler(CommandHandler("reset", reset))

    # Messages texte
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Lancer le bot
    print("✅ Bot prêt ! En attente de messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
