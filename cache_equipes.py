"""
Cache pour CornerAfrik — évite de dépasser le quota gratuit de l'API-Football.

Principe :
  - Les stats de corners d'une équipe (moyenne pour/contre) sont stockées
    dans un fichier local (cache_equipes.json).
  - Elles ne sont RECALCULÉES (donc ne consomment des requêtes API) que si
    elles ont plus de 7 jours, ou si elles n'existent pas encore.
  - Les matchs du jour, eux, sont rafraîchis chaque jour (ça ne coûte
    qu'une requête par championnat, largement dans le quota).

Résultat concret : au lieu de ~220 requêtes/jour, on tombe à quelques
requêtes par jour la plupart du temps (seulement les nouvelles équipes
jamais vues, ou celles dont le cache a expiré).
"""

import json
import os
from datetime import datetime, timedelta

CACHE_FICHIER = "cache_equipes.json"
DUREE_VALIDITE_JOURS = 7


def _charger_cache():
    if not os.path.exists(CACHE_FICHIER):
        return {}
    with open(CACHE_FICHIER, "r", encoding="utf-8") as f:
        return json.load(f)


def _sauvegarder_cache(cache):
    with open(CACHE_FICHIER, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _cle(team_id, domicile):
    return f"{team_id}_{'domicile' if domicile else 'exterieur'}"


def stats_valides_en_cache(team_id, domicile):
    """Renvoie les stats en cache si elles existent et ont moins de 7 jours, sinon None."""
    cache = _charger_cache()
    entree = cache.get(_cle(team_id, domicile))
    if not entree:
        return None

    date_calcul = datetime.fromisoformat(entree["date_calcul"])
    if datetime.now() - date_calcul > timedelta(days=DUREE_VALIDITE_JOURS):
        return None  # expiré, il faudra recalculer

    return entree["stats"]


def enregistrer_stats(team_id, domicile, stats):
    """Sauvegarde les stats fraîchement calculées avec la date du jour."""
    cache = _charger_cache()
    cache[_cle(team_id, domicile)] = {
        "date_calcul": datetime.now().isoformat(),
        "stats": stats,
    }
    _sauvegarder_cache(cache)


def get_stats_equipe(team_id, league_id, saison, domicile, fonction_calcul_api):
    """
    Fonction principale à utiliser partout dans le site.

    - Regarde d'abord le cache.
    - Si rien de valide, appelle fonction_calcul_api (= stats_corners_equipe
      de api_football.py) pour aller chercher les vraies données, PUIS les
      met en cache pour la prochaine fois.

    Exemple d'utilisation :
        from api_football import stats_corners_equipe
        stats = get_stats_equipe(85, 61, 2026, True, stats_corners_equipe)
    """
    stats = stats_valides_en_cache(team_id, domicile)
    if stats is not None:
        return stats, "cache"  # pas de requête API consommée

    stats = fonction_calcul_api(team_id, league_id, saison, domicile=domicile)
    enregistrer_stats(team_id, domicile, stats)
    return stats, "api"  # requêtes API consommées, mais mises en cache pour 7 jours


def statut_cache():
    """Petit résumé utile pour voir combien d'équipes sont en cache et depuis quand."""
    cache = _charger_cache()
    if not cache:
        print("Cache vide.")
        return

    print(f"{len(cache)} entrées en cache :")
    for cle, entree in cache.items():
        date_calcul = datetime.fromisoformat(entree["date_calcul"])
        age_jours = (datetime.now() - date_calcul).days
        expire = " (expiré, sera recalculé)" if age_jours >= DUREE_VALIDITE_JOURS else ""
        print(f"  {cle} — calculé il y a {age_jours}j{expire}")


if __name__ == "__main__":
    statut_cache()
