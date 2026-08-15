"""
API CornerCast — relie le moteur de prédiction (corner_predictor.py) au site web.

Endpoints :
  GET  /api/matchs                 -> liste des matchs du jour avec prédictions
  GET  /api/matchs/<id>             -> détail d'un match
  POST /api/matchs/<id>/override    -> applique une modification manuelle
  POST /api/matchs/<id>/reset       -> annule les modifications, revient au modèle

Lancer avec : python3 app.py
Puis ouvrir : http://localhost:5000/api/matchs
"""

from datetime import date
import sqlite3
import secrets
import os
from flask import Flask, jsonify, request, g, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from corner_predictor import TeamStats, calculer_prediction, LIGNE_PRIORITAIRE

app = Flask(__name__)
CORS(app)  # autorise le site (frontend) à appeler cette API depuis un autre port

MAX_PREDICTIONS_PAR_JOUR = 10
DB_FICHIER = "cornerafrik.db"


@app.route("/")
def accueil():
    # index.html est à la racine du projet, à côté de app.py -> pas besoin
    # de dossier "templates" (plus simple à envoyer depuis un téléphone).
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "index.html")


# ----------------------------------------------------------------------
# BASE DE DONNÉES — COMPTES UTILISATEURS + HISTORIQUE
# (SQLite = un simple fichier, aucune installation de serveur nécessaire)
# ----------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FICHIER)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def fermer_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def initialiser_db():
    db = sqlite3.connect(DB_FICHIER)
    db.execute("""
        CREATE TABLE IF NOT EXISTS utilisateurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pseudo TEXT UNIQUE NOT NULL,
            mot_de_passe_hash TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            date_creation TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS historique (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utilisateur_id INTEGER NOT NULL,
            match_id TEXT NOT NULL,
            ligne REAL NOT NULL,
            pari TEXT NOT NULL,
            resultat TEXT DEFAULT 'en_attente',
            date_pari TEXT NOT NULL,
            FOREIGN KEY (utilisateur_id) REFERENCES utilisateurs (id)
        )
    """)
    db.commit()
    db.close()


def utilisateur_courant():
    """Lit le token dans l'en-tête Authorization et renvoie l'utilisateur correspondant."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        return None
    db = get_db()
    return db.execute("SELECT * FROM utilisateurs WHERE token = ?", (token,)).fetchone()


# ----------------------------------------------------------------------
# ROUTES — COMPTES UTILISATEURS
# ----------------------------------------------------------------------

@app.route("/api/inscription", methods=["POST"])
def inscription():
    data = request.get_json(force=True)
    pseudo = (data.get("pseudo") or "").strip()
    mot_de_passe = data.get("mot_de_passe") or ""

    if len(pseudo) < 3:
        return jsonify({"erreur": "Le pseudo doit faire au moins 3 caractères"}), 400
    if len(mot_de_passe) < 6:
        return jsonify({"erreur": "Le mot de passe doit faire au moins 6 caractères"}), 400

    db = get_db()
    existe = db.execute("SELECT id FROM utilisateurs WHERE pseudo = ?", (pseudo,)).fetchone()
    if existe:
        return jsonify({"erreur": "Ce pseudo est déjà pris"}), 409

    token = secrets.token_hex(24)
    db.execute(
        "INSERT INTO utilisateurs (pseudo, mot_de_passe_hash, token, date_creation) VALUES (?, ?, ?, ?)",
        (pseudo, generate_password_hash(mot_de_passe), token, date.today().isoformat()),
    )
    db.commit()
    return jsonify({"pseudo": pseudo, "token": token})


@app.route("/api/connexion", methods=["POST"])
def connexion():
    data = request.get_json(force=True)
    pseudo = (data.get("pseudo") or "").strip()
    mot_de_passe = data.get("mot_de_passe") or ""

    db = get_db()
    utilisateur = db.execute("SELECT * FROM utilisateurs WHERE pseudo = ?", (pseudo,)).fetchone()
    if not utilisateur or not check_password_hash(utilisateur["mot_de_passe_hash"], mot_de_passe):
        return jsonify({"erreur": "Pseudo ou mot de passe incorrect"}), 401

    return jsonify({"pseudo": utilisateur["pseudo"], "token": utilisateur["token"]})


@app.route("/api/mon-historique", methods=["GET"])
def mon_historique():
    utilisateur = utilisateur_courant()
    if not utilisateur:
        return jsonify({"erreur": "Non connecté"}), 401

    db = get_db()
    lignes = db.execute(
        "SELECT * FROM historique WHERE utilisateur_id = ? ORDER BY date_pari DESC",
        (utilisateur["id"],),
    ).fetchall()

    reussis = sum(1 for l in lignes if l["resultat"] == "gagne")
    total_juges = sum(1 for l in lignes if l["resultat"] in ("gagne", "perdu"))

    return jsonify({
        "pseudo": utilisateur["pseudo"],
        "taux_reussite": round(reussis / total_juges * 100) if total_juges else None,
        "historique": [dict(l) for l in lignes],
    })


@app.route("/api/mon-historique/ajouter", methods=["POST"])
def ajouter_historique():
    """L'utilisateur enregistre son propre pari (après avoir vu ou modifié une prédiction)."""
    utilisateur = utilisateur_courant()
    if not utilisateur:
        return jsonify({"erreur": "Non connecté"}), 401

    data = request.get_json(force=True)
    db = get_db()
    db.execute(
        "INSERT INTO historique (utilisateur_id, match_id, ligne, pari, date_pari) VALUES (?, ?, ?, ?, ?)",
        (utilisateur["id"], data.get("match_id"), data.get("ligne"), data.get("pari"), date.today().isoformat()),
    )
    db.commit()
    return jsonify({"statut": "enregistré"})


initialiser_db()


# ----------------------------------------------------------------------
# BASE D'ÉQUIPES DE DÉMONSTRATION
# (à remplacer plus tard par des appels à l'API-Football en direct)
# ----------------------------------------------------------------------

EQUIPES = {
    "psg":       TeamStats("PSG", 6.8, 5.1, 3.2, 4.0),
    "om":        TeamStats("Marseille", 5.5, 4.3, 3.9, 4.8),
    "arsenal":   TeamStats("Arsenal", 7.1, 5.8, 3.0, 3.6),
    "chelsea":   TeamStats("Chelsea", 6.2, 5.0, 3.5, 4.1),
    "real":      TeamStats("Real Madrid", 6.4, 5.6, 2.9, 3.8),
    "betis":     TeamStats("Betis", 4.8, 3.9, 4.2, 5.0),
    "bayern":    TeamStats("Bayern", 7.4, 6.0, 2.7, 3.4),
    "dortmund":  TeamStats("Dortmund", 6.0, 5.2, 3.6, 4.4),
    "cotedivoire": TeamStats("Côte d'Ivoire", 5.0, 4.2, 3.8, 4.5),
    "burkina":   TeamStats("Burkina Faso", 4.4, 3.6, 4.0, 4.9),
}

# ----------------------------------------------------------------------
# MATCHS DU JOUR (démo) — chaque match garde son propre objet MatchPrediction
# en mémoire, pour que les overrides persistent tant que le serveur tourne.
#
# Les dates sont calculées par rapport à AUJOURD'HUI (et non figées) pour que
# la démo fonctionne peu importe le jour où tu lances le serveur. Une fois
# l'API-Football branchée (voir api_football.py), ces dates viendront des
# vrais matchs du jour au lieu d'être générées ici.
# ----------------------------------------------------------------------

AUJOURD_HUI = date.today().isoformat()

MATCHS = {
    "1": {"championnat": "Premier League", "domicile": "arsenal", "exterieur": "chelsea", "date": AUJOURD_HUI},
    "2": {"championnat": "Ligue 1", "domicile": "psg", "exterieur": "om", "date": AUJOURD_HUI},
    "3": {"championnat": "Liga", "domicile": "real", "exterieur": "betis", "date": AUJOURD_HUI},
    "4": {"championnat": "Bundesliga", "domicile": "bayern", "exterieur": "dortmund", "date": AUJOURD_HUI},
    "5": {"championnat": "CAF Éliminatoires", "domicile": "cotedivoire", "exterieur": "burkina", "date": AUJOURD_HUI},
}

# Cache des prédictions déjà calculées (garde les overrides en mémoire)
_predictions_cache = {}


def get_prediction(match_id):
    if match_id not in _predictions_cache:
        info = MATCHS[match_id]
        domicile = EQUIPES[info["domicile"]]
        exterieur = EQUIPES[info["exterieur"]]
        _predictions_cache[match_id] = calculer_prediction(domicile, exterieur)
    return _predictions_cache[match_id]


def serialiser(match_id, prediction):
    info = MATCHS[match_id]
    return {
        "id": match_id,
        "championnat": info["championnat"],
        "date": info["date"],
        "equipe_domicile": prediction.equipe_domicile,
        "equipe_exterieur": prediction.equipe_exterieur,
        "corners_predits": round(prediction.corners_predits_final, 1),
        "modifie_manuellement": prediction.modifie_manuellement,
        "note_analyse": prediction.note_analyse,
        "ligne_prioritaire": LIGNE_PRIORITAIRE,
        "lignes": [
            {"ligne": lp.ligne, "pari": lp.pari, "confiance": round(lp.probabilite_plus * 100)}
            for lp in prediction.lignes_final
        ],
    }


# ----------------------------------------------------------------------
# SÉLECTION DES MATCHS DU JOUR
# ----------------------------------------------------------------------

def confiance_9_5(prediction):
    """Score de fiabilité utilisé pour classer les matchs : plus la probabilité
    sur la ligne prioritaire (9.5) s'éloigne de 50%, plus la prédiction est nette."""
    ligne = next(lp for lp in prediction.lignes_final if lp.ligne == LIGNE_PRIORITAIRE)
    return abs(ligne.probabilite_plus - 0.5)


def matchs_du_jour(date_cible=None, max_predictions=MAX_PREDICTIONS_PAR_JOUR):
    """
    Ne garde que les matchs programmés à date_cible (aujourd'hui par défaut),
    triés du plus fiable au moins fiable, et coupe à max_predictions.
    S'il y a moins de matchs que max_predictions ce jour-là, on renvoie tout
    ce qui est disponible (ex: un mardi calme -> 3 ou 4 seulement).
    """
    date_cible = date_cible or date.today().isoformat()

    matchs_ids = [mid for mid, info in MATCHS.items() if info["date"] == date_cible]
    predictions = [(mid, get_prediction(mid)) for mid in matchs_ids]
    predictions.sort(key=lambda item: confiance_9_5(item[1]), reverse=True)

    return predictions[:max_predictions]


# ----------------------------------------------------------------------
# ROUTES
# ----------------------------------------------------------------------

@app.route("/api/matchs", methods=["GET"])
def liste_matchs():
    """
    Renvoie uniquement les matchs du jour (paramètre ?date=YYYY-MM-DD pour tester
    un autre jour), limités aux 10 prédictions les plus fiables.
    """
    date_cible = request.args.get("date")
    selection = matchs_du_jour(date_cible)
    resultat = [serialiser(mid, prediction) for mid, prediction in selection]
    return jsonify({
        "date": date_cible or date.today().isoformat(),
        "nombre_matchs": len(resultat),
        "matchs": resultat,
    })


@app.route("/api/matchs/<match_id>", methods=["GET"])
def detail_match(match_id):
    if match_id not in MATCHS:
        return jsonify({"erreur": "Match introuvable"}), 404
    return jsonify(serialiser(match_id, get_prediction(match_id)))


@app.route("/api/matchs/<match_id>/override", methods=["POST"])
def override_match(match_id):
    """
    Corps de la requête attendu (JSON), ex :
    {
      "lignes": {"9.5": "MOINS", "8.5": "PLUS"},
      "corners_predits": 8.0,
      "note": "Titulaire absent, j'ai vu la compo"
    }
    """
    if match_id not in MATCHS:
        return jsonify({"erreur": "Match introuvable"}), 404

    data = request.get_json(force=True)
    prediction = get_prediction(match_id)

    lignes_brutes = data.get("lignes", {})
    lignes = {float(k): v for k, v in lignes_brutes.items()}  # les clés JSON sont des strings

    prediction.appliquer_override(
        corners_predits=data.get("corners_predits"),
        lignes=lignes,
        note=data.get("note", ""),
    )
    return jsonify(serialiser(match_id, prediction))


@app.route("/api/matchs/<match_id>/reset", methods=["POST"])
def reset_match(match_id):
    if match_id not in MATCHS:
        return jsonify({"erreur": "Match introuvable"}), 404
    prediction = get_prediction(match_id)
    prediction.reinitialiser()
    return jsonify(serialiser(match_id, prediction))


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
