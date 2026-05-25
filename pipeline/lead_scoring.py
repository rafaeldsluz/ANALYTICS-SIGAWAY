"""
Lead scoring — calculates a 0-100 score and tier based on digital presence.

Tiers:
  frio    :  0-24
  morno   : 25-49
  quente  : 50-74
  premium : 75-100
"""


def calculate_score(lead: dict) -> dict:
    """Returns {"score": int, "tier": str}."""
    score = 0

    # Website (+20)
    if (lead.get("website") or "").strip():
        score += 20

    # Google Maps presence (+15) and quality bonuses
    has_maps = (lead.get("google_rating") or "").strip() or (lead.get("maps_link") or "").strip()
    if has_maps:
        score += 15
        try:
            rating = float(str(lead.get("google_rating", "0")).replace(",", "."))
            if rating >= 4.0:
                score += 10
        except (ValueError, TypeError):
            pass
        try:
            reviews = int(str(lead.get("google_reviews", "0")).replace(".", "").replace(",", ""))
            if reviews >= 10:
                score += 5
        except (ValueError, TypeError):
            pass

    # Instagram presence (+20) and quality bonuses
    if (lead.get("instagram") or "").strip():
        score += 20
        try:
            followers = int(lead.get("instagram_followers") or 0)
            if followers >= 500:
                score += 5
        except (ValueError, TypeError):
            pass
        if lead.get("instagram_verified"):
            score += 10

    # LinkedIn presence (+15)
    if (lead.get("linkedin") or "").strip():
        score += 15

    # Company size bonus
    porte = (lead.get("porte") or "").upper()
    if "GRANDE" in porte:
        score += 5
    elif "MEDIO" in porte or "MÉDIO" in porte or "MEDIA" in porte:
        score += 3
    elif "PEQUENO" in porte or "MICRO" in porte:
        score += 1

    score = min(score, 100)

    if score >= 75:
        tier = "premium"
    elif score >= 50:
        tier = "quente"
    elif score >= 25:
        tier = "morno"
    else:
        tier = "frio"

    return {"score": score, "tier": tier}
