"""Turn a user's stated locations into per-provider geo parameters.

A public product serves users in many countries, so nothing here may be
hardcoded to one market. Adzuna's endpoint is per-country and Careerjet's
locale is per-country; both must follow the *user's* profile, not a global
env default. These helpers map free-text locations ("Milan", "Remote-US",
"United Kingdom") onto the codes those APIs expect.
"""

from __future__ import annotations

import re

from .config import Profile

# Countries Adzuna exposes an endpoint for (ISO-3166 alpha-2, their codes).
ADZUNA_COUNTRIES = {
    "at", "au", "be", "br", "ca", "ch", "de", "es", "fr", "gb", "in", "it",
    "mx", "nl", "nz", "pl", "sg", "us", "za",
}

# Location text -> country code. Country names, common variants, and the major
# cities people actually type. Unknown tokens resolve to nothing (skipped),
# never to a wrong country.
_COUNTRY_ALIASES = {
    "us": "us", "usa": "us", "united states": "us", "america": "us", "u.s.": "us",
    "u.s.a.": "us", "states": "us",
    "uk": "gb", "u.k.": "gb", "united kingdom": "gb", "great britain": "gb",
    "britain": "gb", "england": "gb", "scotland": "gb", "wales": "gb", "gb": "gb",
    "italy": "it", "italia": "it", "it": "it",
    "germany": "de", "deutschland": "de", "de": "de",
    "france": "fr", "fr": "fr",
    "spain": "es", "españa": "es", "espana": "es", "es": "es",
    "netherlands": "nl", "holland": "nl", "nl": "nl",
    "belgium": "be", "austria": "at", "switzerland": "ch", "schweiz": "ch",
    "poland": "pl", "polska": "pl",
    "canada": "ca", "australia": "au", "new zealand": "nz",
    "india": "in", "singapore": "sg", "brazil": "br", "brasil": "br",
    "mexico": "mx", "méxico": "mx",
    "south africa": "za",
    # Not Adzuna endpoints, but valid for Careerjet (~90 countries) and for
    # matching a posting's location by name.
    "ireland": "ie", "portugal": "pt", "sweden": "se", "denmark": "dk",
    "norway": "no", "finland": "fi", "greece": "gr", "romania": "ro",
    "czechia": "cz", "czech republic": "cz", "japan": "jp",
    "united arab emirates": "ae", "uae": "ae",
}

# Major cities -> country. Kept to ones people commonly enter; a miss just
# means that token contributes no country, which is safe.
_CITY_COUNTRY = {
    "new york": "us", "nyc": "us", "san francisco": "us", "sf": "us",
    "los angeles": "us", "la": "us", "chicago": "us", "boston": "us",
    "seattle": "us", "austin": "us", "denver": "us", "miami": "us",
    "washington": "us", "atlanta": "us", "dallas": "us",
    "london": "gb", "manchester": "gb", "edinburgh": "gb", "bristol": "gb",
    "leeds": "gb", "glasgow": "gb", "birmingham": "gb", "liverpool": "gb",
    "sheffield": "gb", "cardiff": "gb", "belfast": "gb", "nottingham": "gb",
    "newcastle": "gb", "southampton": "gb", "oxford": "gb", "cambridge": "gb",
    "reading": "gb", "brighton": "gb", "aberdeen": "gb", "hampshire": "gb",
    "surrey": "gb", "yorkshire": "gb",
    "milan": "it", "milano": "it", "rome": "it", "roma": "it", "turin": "it",
    "torino": "it", "bologna": "it", "florence": "it", "naples": "it",
    "genoa": "it", "genova": "it", "palermo": "it", "catania": "it",
    "venice": "it", "venezia": "it", "verona": "it", "padua": "it",
    "padova": "it", "bari": "it", "brescia": "it", "modena": "it",
    "parma": "it", "bergamo": "it", "trieste": "it",
    "hong kong": "hk", "dubai": "ae", "abu dhabi": "ae",
    "berlin": "de", "munich": "de", "münchen": "de", "hamburg": "de",
    "frankfurt": "de", "cologne": "de",
    "paris": "fr", "lyon": "fr",
    "madrid": "es", "barcelona": "es",
    "amsterdam": "nl", "rotterdam": "nl",
    "toronto": "ca", "vancouver": "ca", "montreal": "ca",
    "sydney": "au", "melbourne": "au",
    "zurich": "ch", "geneva": "ch",
    "vienna": "at", "brussels": "be", "warsaw": "pl",
    "bangalore": "in", "bengaluru": "in", "mumbai": "in", "delhi": "in",
}

# Careerjet wants lang_COUNTRY. Sensible default language per country.
_CAREERJET_LOCALE = {
    "us": "en_US", "gb": "en_GB", "ca": "en_CA", "au": "en_AU", "nz": "en_NZ",
    "in": "en_IN", "sg": "en_SG", "za": "en_ZA",
    "it": "it_IT", "de": "de_DE", "fr": "fr_FR", "es": "es_ES",
    "nl": "nl_NL", "be": "fr_BE", "at": "de_AT", "ch": "de_CH",
    "pl": "pl_PL", "br": "pt_BR", "mx": "es_MX",
    "ie": "en_IE", "pt": "pt_PT", "se": "sv_SE", "dk": "da_DK",
    "no": "no_NO", "fi": "fi_FI", "gr": "el_GR", "ro": "ro_RO",
    "cz": "cs_CZ", "jp": "ja_JP", "ae": "en_AE",
}


def _country_of(token: str) -> str:
    """Best-effort country code for one location string, or ""."""
    t = token.strip().lower()
    if not t:
        return ""
    # "Remote-US", "Remote-Italy" -> the region after the dash.
    if t.startswith("remote"):
        t = t.split("-", 1)[1].strip() if "-" in t else ""
        if not t:
            return ""
    if t in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[t]
    if t in _CITY_COUNTRY:
        return _CITY_COUNTRY[t]
    # "Milan, Italy" / "Austin, TX, US" -> try each comma-separated part.
    parts = [p.strip() for p in re.split(r"[,/|]", t) if p.strip()]
    if len(parts) > 1:
        for p in parts:
            c = _COUNTRY_ALIASES.get(p) or _CITY_COUNTRY.get(p)
            if c:
                return c
    return ""


def countries(profile: Profile, limit: int = 3) -> list[str]:
    """Distinct Adzuna country codes implied by the profile, best first.

    Order follows the profile so the user's primary market leads. Empty when
    nothing resolves — the caller then falls back to its configured default.
    """
    out: list[str] = []
    for loc in profile.locations:
        code = _country_of(loc)
        if code in ADZUNA_COUNTRIES and code not in out:
            out.append(code)
        if len(out) >= limit:
            break
    return out


def google_locale(location: str) -> tuple[str, str]:
    """(gl, hl) for Google-for-Jobs: the country code and UI language for a place.

    Without these, SerpApi's google_jobs defaults toward US/English and returns
    nothing for a non-English market — an Italy search needs gl=it, hl=it.
    """
    code = _country_of(location)
    if not code:
        return ("", "en")
    locale = _CAREERJET_LOCALE.get(code, "en_" + code.upper())
    return (code, locale.split("_")[0])


def careerjet_locale(profile: Profile, default: str = "en_GB") -> str:
    """Careerjet locale for the profile's primary country."""
    for loc in profile.locations:
        code = _country_of(loc)
        if code in _CAREERJET_LOCALE:
            return _CAREERJET_LOCALE[code]
    return default


# Country code -> substrings that indicate a posting is in that country.
# Built by inverting the name/city maps so there's one source of geo truth.
# Short aliases (<=3 chars, e.g. "us", "uk", "sf") are excluded: as substrings
# they match unrelated words ("us" inside "Houston"), causing false positives.
_CODE_TO_ALIASES: dict[str, list[str]] = {}
for _name, _code in _COUNTRY_ALIASES.items():
    if len(_name) >= 4:
        _CODE_TO_ALIASES.setdefault(_code, []).append(_name)
for _city, _code in _CITY_COUNTRY.items():
    if len(_city) >= 4:
        _CODE_TO_ALIASES.setdefault(_code, []).append(_city)

# Short country codes that DO appear in real job locations ("London, UK",
# "Remote US"). Matched only as WHOLE WORDS, so they catch a bare "UK"/"US"
# without the substring false positives above. The ambiguous ones — "de"/"es"/
# "it", which are ordinary words inside place names ("Rio de Janeiro") — are
# deliberately left out; those countries are still caught by their full name or
# a city. This closes the leak where a bare "UK" slipped past an Italy filter.
_AMBIGUOUS_SHORT = {"de", "es", "it"}
_CODE_TO_SHORT: dict[str, list[str]] = {}
for _name, _code in _COUNTRY_ALIASES.items():
    if len(_name) <= 3 and _name.isalpha() and _name not in _AMBIGUOUS_SHORT:
        _CODE_TO_SHORT.setdefault(_code, []).append(_name)

# US state abbreviations that appear in job locations ("Clearwater, FL"), mapped
# to the US and matched as WHOLE WORDS. Curated to avoid (a) codes that clash with
# a country we support (CA=Canada, IN=India, DE=Germany, ID~Indonesia) and (b) ones
# that are ordinary words or appear inside place names (OR, OK, HI, ME, LA, MA, AL,
# CO="County", OH), which as whole words would wrongly flag a home-country city.
_US_STATE_CODES = [
    "fl", "tx", "ny", "nj", "pa", "ga", "nc", "sc", "tn", "va", "wa", "wi",
    "wv", "wy", "ut", "nv", "nm", "ne", "nh", "ks", "ky", "ct", "az", "ar",
    "ak", "mn", "mo", "ms", "mt", "md", "ri", "vt", "nd", "sd",
]
_CODE_TO_SHORT.setdefault("us", []).extend(_US_STATE_CODES)


def _names_short_code(loc_hay: str, code: str) -> bool:
    """True if `loc_hay` contains a whole-word short alias for `code`."""
    for short in _CODE_TO_SHORT.get(code, []):
        if re.search(r"\b" + re.escape(short) + r"\b", loc_hay):
            return True
    return False


def is_country_name(token: str) -> bool:
    """True if `token` names a country, not merely a city.

    Lets the location filter be permissive for a country preference ("keep
    unlisted cities of that country") but strict for a city preference ("Milan
    means Milan"), so a global corpus doesn't leak foreign cities into a
    city-scoped search.
    """
    return token.strip().lower() in _COUNTRY_ALIASES


def country_of(text: str) -> str:
    """Public: best-effort ISO country code for a location string, or "".

    Handles "Milan, Italy", "Austin, TX, US", bare country names and cities.
    """
    return _country_of(text)


def location_in_countries(loc_hay: str, codes) -> bool:
    """True if the location text names any city/country of the given codes.

    Used to tell whether a remote job's stated place is inside a target region
    ("Berlin" → Germany → inside EU) via the same city/country aliases the rest
    of the filter uses.
    """
    for code in codes:
        if any(a in loc_hay for a in _CODE_TO_ALIASES.get(code, [])):
            return True
    return False


def names_other_country(loc_hay: str, token: str) -> bool:
    """True if `loc_hay` clearly names a country other than `token`'s.

    Lets a country preference keep a posting whose location is an unlisted city
    ("Houston" for a US preference — names no other country, so plausibly US)
    while still rejecting one that names a different country ("Milan, Italy").
    """
    own = _country_of(token)
    for code, aliases in _CODE_TO_ALIASES.items():
        if code == own:
            continue
        if any(a in loc_hay for a in aliases):
            return True
    # Bare short codes ("UK", "US"), matched as whole words only.
    for code in _CODE_TO_SHORT:
        if code != own and _names_short_code(loc_hay, code):
            return True
    return False


def match_aliases(token: str) -> list[str]:
    """Substrings that, found in a job's location, mean it's in `token`'s place.

    For a recognised country this is its name variants plus major cities, so a
    US preference matches "Austin, TX" and an Italy preference matches "Milano".
    For anything unrecognised it's just the token itself (lower-cased).
    """
    t = token.strip().lower()
    if not t:
        return []
    code = _country_of(t)
    if code and code in _CODE_TO_ALIASES:
        aliases = list(_CODE_TO_ALIASES[code])
        if t not in aliases and len(t) >= 4:
            aliases.append(t)
        return aliases
    return [t]
