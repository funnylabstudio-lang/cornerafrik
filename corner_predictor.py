"""
Prototype de l'algorithme de prédiction de corners — CornerCast

Logique :
  1. Le modèle calcule une prédiction brute (nombre de corners + probabilités par ligne)
  2. L'utilisateur peut ANALYSER LUI-MÊME le coupon et ÉCRASER la prédiction du modèle
  3. On garde toujours les deux valeurs séparées (modèle vs override) pour pouvoir
     comparer les performances dans le temps (qui a raison : l'algo ou l'analyse manuelle ?)
"""

from dataclasses import dataclass, field
from datetime import datetime
from statistics import NormalDist

LINES = [5.5, 6.5, 7.5, 8.5, 9.5]
LIGNE_PRIORITAIRE = 9.5  # la plus jouée par les utilisateurs -> mise en avant


# ----------------------------------------------------------------------
# 1. STRUCTURE DE DONNÉES D'UNE ÉQUIPE (viendra de l'API de stats plus tard)
# ----------------------------------------------------------------------

@dataclass
class TeamStats:
    name: str
    corners_pour_domicile: float      # moyenne corners obtenus à domicile
    corners_pour_exterieur: float     # moyenne corners obtenus à l'extérieur
    corners_contre_domicile: float    # moyenne corners concédés à domicile
    corners_contre_exterieur: float   # moyenne corners concédés à l'extérieur
    ecart_type: float = 2.1           # variance historique du nombre de corners


# ----------------------------------------------------------------------
# 2. PRÉDICTION DU MODÈLE
# ----------------------------------------------------------------------

@dataclass
class LinePrediction:
    ligne: float
    probabilite_plus: float   # probabilité que le total dépasse la ligne (0-1)
    pari: str                 # "PLUS" ou "MOINS"


@dataclass
class MatchPrediction:
    equipe_domicile: str
    equipe_exterieur: str
    corners_predits_modele: float
    lignes_modele: list  # list[LinePrediction]
    date_calcul: datetime = field(default_factory=datetime.now)

    # --- champs d'override (remplis seulement si l'utilisateur modifie) ---
    corners_predits_final: float = None
    lignes_final: list = None
    modifie_manuellement: bool = False
    note_analyse: str = ""

    def __post_init__(self):
        # Par défaut, la valeur "finale" = valeur du modèle, tant que
        # l'utilisateur n'a rien modifié.
        if self.corners_predits_final is None:
            self.corners_predits_final = self.corners_predits_modele
        if self.lignes_final is None:
            self.lignes_final = list(self.lignes_modele)

    def appliquer_override(self, corners_predits: float = None, lignes: dict = None, note: str = ""):
        """
        L'utilisateur écrase la prédiction après sa propre analyse du coupon.

        - corners_predits : nouveau total de corners prédits (optionnel)
        - lignes : dict {ligne: "PLUS"/"MOINS"} pour changer un ou plusieurs paris
                   ex: {9.5: "MOINS", 8.5: "PLUS"}
        - note : pourquoi tu changes (utile pour te relire plus tard)
        """
        self.modifie_manuellement = True
        self.note_analyse = note or self.note_analyse

        if corners_predits is not None:
            self.corners_predits_final = corners_predits

        if lignes:
            nouvelles_lignes = []
            for lp in self.lignes_final:
                if lp.ligne in lignes:
                    nouveau_pari = lignes[lp.ligne]
                    nouvelles_lignes.append(
                        LinePrediction(ligne=lp.ligne, probabilite_plus=lp.probabilite_plus, pari=nouveau_pari)
                    )
                else:
                    nouvelles_lignes.append(lp)
            self.lignes_final = nouvelles_lignes

    def reinitialiser(self):
        """Annule tes modifications et revient à la prédiction pure du modèle."""
        self.corners_predits_final = self.corners_predits_modele
        self.lignes_final = list(self.lignes_modele)
        self.modifie_manuellement = False
        self.note_analyse = ""

    def resume(self):
        lignes_txt = "  ".join(f"{lp.ligne} → {lp.pari} ({lp.probabilite_plus*100:.0f}%)" for lp in self.lignes_final)
        source = "TOI (override)" if self.modifie_manuellement else "MODÈLE"
        featured = next(lp for lp in self.lignes_final if lp.ligne == LIGNE_PRIORITAIRE)
        print(f"\n{self.equipe_domicile} — {self.equipe_exterieur}")
        print(f"  Corners prédits : {self.corners_predits_final:.1f}  [source: {source}]")
        print(f"  Lignes : {lignes_txt}")
        print(f"  >> Ligne prioritaire (9.5) : {featured.pari} — c'est celle-ci qui compte le plus pour les users")
        if self.note_analyse:
            print(f"  Note : {self.note_analyse}")


# ----------------------------------------------------------------------
# 3. CALCUL DE LA PRÉDICTION BRUTE
# ----------------------------------------------------------------------

def calculer_prediction(domicile: TeamStats, exterieur: TeamStats) -> MatchPrediction:
    # Corners prédits domicile = moyenne de ce que l'équipe A obtient chez elle
    #                              et de ce que l'équipe B concède à l'extérieur
    corners_domicile = (domicile.corners_pour_domicile + exterieur.corners_contre_exterieur) / 2
    corners_exterieur = (exterieur.corners_pour_exterieur + domicile.corners_contre_domicile) / 2
    total_predit = corners_domicile + corners_exterieur

    # Variance combinée (approximation simple)
    ecart_type_combine = ((domicile.ecart_type ** 2 + exterieur.ecart_type ** 2) ** 0.5)

    lignes = []
    for ligne in LINES:
        # Probabilité que le total dépasse la ligne, via loi normale
        z = (ligne - total_predit) / ecart_type_combine
        proba_moins = NormalDist().cdf(z)
        proba_plus = 1 - proba_moins
        pari = "PLUS" if proba_plus >= 0.5 else "MOINS"
        lignes.append(LinePrediction(ligne=ligne, probabilite_plus=proba_plus, pari=pari))

    return MatchPrediction(
        equipe_domicile=domicile.name,
        equipe_exterieur=exterieur.name,
        corners_predits_modele=total_predit,
        lignes_modele=lignes,
    )


# ----------------------------------------------------------------------
# 4. EXEMPLE D'UTILISATION
# ----------------------------------------------------------------------

if __name__ == "__main__":
    psg = TeamStats(
        name="PSG",
        corners_pour_domicile=6.8,
        corners_pour_exterieur=5.1,
        corners_contre_domicile=3.2,
        corners_contre_exterieur=4.0,
    )
    om = TeamStats(
        name="Marseille",
        corners_pour_domicile=5.5,
        corners_pour_exterieur=4.3,
        corners_contre_domicile=3.9,
        corners_contre_exterieur=4.8,
    )

    prediction = calculer_prediction(psg, om)
    print("=== Prédiction du modèle ===")
    prediction.resume()

    # --- Exemple : toi, après avoir regardé le coupon et les compos,
    #     tu penses que le 9.5 va tomber MOINS alors que le modèle dit PLUS ---
    prediction.appliquer_override(
        lignes={9.5: "MOINS"},
        note="Kylian absent, PSG a tourné son effectif hier en coupe -> moins de rythme offensif",
    )

    print("\n=== Après ton analyse manuelle ===")
    prediction.resume()
