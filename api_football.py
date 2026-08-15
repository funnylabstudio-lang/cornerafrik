"""
Connexion à l'API-Football (api-sports.io) pour CornerAfrik.

ÉTAPES POUR OBTENIR TA CLÉ (gratuit, sans carte bancaire) :
  1. Va sur https://www.api-football.com/
  2. Crée un compte
  3. Récupère ta clé dans ton dashboard ("API Key")
  4. Colle-la ci-dessous dans API_KEY, ou mets-la en variable d'environnement

LIMITE DU PLAN GRATUIT : 100 requêtes par jour (remis à zéro à minuit UTC).
=> Ce fichier est conçu pour limiter les appels : il calcule les stats
   moyennes d'une équipe en UNE seule requête par équipe (les 10 derniers
   matchs), pas un appel par match.
"""

import os
import requests
from statistics import mean

API_KEY = os.environ.get("API_FOOTBALL_KEY", "COLLE_TA_CLE_ICI")
BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# IDs des championnats sur API-Football (à ajuster selon ceux que tu veux couvrir)
CHAMPIONNATS = {
    "Ligue 1": 61,
    "Premier League": 39,
    "Liga": 140,
    "Bundesliga": 78,
    "Serie A": 135,
    "Champions League": 2,
    "CAF Éliminatoires Mondial": 29,
}


def matchs_du_jour(date_str):
    """
    Récupère tous les matchs programmés à une date donnée (format YYYY-MM-DD),
    filtrés sur les championnats qu'on couvre.
    Coût : 1 requête par championnat suivi.
    """
    tous_les_matchs = []
    for nom_championnat, league_id in CHAMPIONNATS.items():
        params = {"date": date_str, "league": league_id, "season": date_str[:4]}
        reponse = requests.get(f"{BASE_URL}/fixtures", headers=HEADERS, params=params)
        reponse.raise_for_status()
        data = reponse.json()

        for match in data.get("response", []):
            tous_les_matchs.append({
                "id": match["fixture"]["id"],
                "championnat": nom_championnat,
                "equipe_domicile": match["teams"]["home"]["name"],
                "equipe_domicile_id": match["teams"]["home"]["id"],
                "equipe_exterieur": match["teams"]["away"]["name"],
                "equipe_exterieur_id": match["teams"]["away"]["id"],
                "date": match["fixture"]["date"],
            })
    return tous_les_matchs


def stats_corners_equipe(team_id, league_id, saison, domicile=True, nb_matchs=10):
    """
    Calcule la moyenne de corners obtenus ET concédés par une équipe sur ses
    N derniers matchs à domicile ou à l'extérieur.

    Coût : 1 requête pour la liste des matchs + 1 requête par match pour les stats
    (ex: 10 derniers matchs = 11 requêtes). C'est ce qui consomme le plus ton quota
    -> pense à mettre ces résultats en cache (voir note en bas de fichier).
    """
    params = {
        "team": team_id,
        "league": league_id,
        "season": saison,
        "last": nb_matchs,
        "venue": "home" if domicile else "away",
    }
    reponse = requests.get(f"{BASE_URL}/fixtures", headers=HEADERS, params=params)
    reponse.raise_for_status()
    matchs = reponse.json().get("response", [])

    corners_pour = []
    corners_contre = []

    for match in matchs:
        fixture_id = match["fixture"]["id"]
        stats_reponse = requests.get(
            f"{BASE_URL}/fixtures/statistics",
            headers=HEADERS,
            params={"fixture": fixture_id},
        )
        stats_reponse.raise_for_status()
        stats_data = stats_reponse.json().get("response", [])

        for equipe_stats in stats_data:
            corners = next(
                (s["value"] for s in equipe_stats["statistics"] if s["type"] == "Corner Kicks"),
                None,
            )
            if corners is None:
                continue
            if equipe_stats["team"]["id"] == team_id:
                corners_pour.append(corners)
            else:
                corners_contre.append(corners)

    return {
        "corners_pour_moyenne": mean(corners_pour) if corners_pour else None,
        "corners_contre_moyenne": mean(corners_contre) if corners_contre else None,
        "matchs_analyses": len(matchs),
    }


# ----------------------------------------------------------------------
# NOTE SUR LE QUOTA (plan gratuit = 100 requêtes/jour)
# ----------------------------------------------------------------------
# Calculer les stats d'UNE SEULE équipe sur 10 matchs = 11 requêtes.
# Pour 10 matchs du jour = 20 équipes à analyser = ~220 requêtes.
# ÇA DÉPASSE LE QUOTA GRATUIT.
#
# Solutions concrètes :
#   1. Ne recalculer les stats d'une équipe qu'une fois par semaine (pas
#      chaque jour) et les stocker (base de données ou simple fichier JSON),
#      puisque les moyennes ne changent pas beaucoup d'un jour à l'autre.
#   2. Ou passer à un plan payant d'API-Football une fois que le site a
#      des utilisateurs et génère des revenus.
#   3. En attendant, commence avec 2-3 championnats et peu d'équipes pour
#      rester sous les 100 requêtes/jour pendant les tests.


if __name__ == "__main__":
    # Exemple d'utilisation (nécessite une vraie clé API pour fonctionner)
    matchs = matchs_du_jour("2026-08-15")
    print(f"{len(matchs)} matchs trouvés aujourd'hui")
    for m in matchs[:5]:
        print(f"  {m['championnat']} : {m['equipe_domicile']} - {m['equipe_exterieur']}")
