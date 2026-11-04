"""
Geocoding degli indirizzi dei lead -> coordinate (lat, lng).

Provider (variabile d'ambiente GEOCODER):
  - "nominatim" (default): servizio pubblico di OpenStreetMap. Gratuito ma con
    regole d'uso rigide: massimo 1 richiesta al secondo e User-Agent che
    identifica l'applicazione. Questo modulo rispetta entrambe.
    Imposta GEOCODER_CONTACT_EMAIL con un tuo indirizzo email (finisce
    nello User-Agent, come richiesto dalle regole di Nominatim).
  - "geoapify": serve una chiave in GEOAPIFY_KEY. Piu' veloce, ha un piano
    gratuito con limite giornaliero: controlla sul loro sito limiti e
    condizioni (anche sul salvataggio dei risultati) prima di usarlo in massa.

Nessuna dipendenza esterna: usa solo la libreria standard.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

PROVIDER = os.environ.get("GEOCODER", "nominatim").strip().lower()
GEOAPIFY_KEY = os.environ.get("GEOAPIFY_KEY", "").strip()
CONTACT = os.environ.get("GEOCODER_CONTACT_EMAIL", "").strip()
USER_AGENT = "CRM-Lead-PropertiesFinding/1.0" + (f" ({CONTACT})" if CONTACT else "")

# Pausa minima tra due richieste allo stesso servizio
_MIN_INTERVAL = {"nominatim": 1.1, "geoapify": 0.25}
_throttle_lock = threading.Lock()
_last_call = 0.0

# Riquadro che contiene l'Italia: risultati fuori da qui vengono scartati
# (protegge da omonimie, es. una "Via Roma" trovata in un altro Paese).
ITALIA_LAT = (35.4, 47.2)
ITALIA_LNG = (6.5, 18.9)


class GeocodeTemporaryError(Exception):
    """Errore temporaneo (rete, limite di richieste, servizio giu'): riprovare piu' tardi."""


def build_query(indirizzo, citta):
    """Costruisce la stringa da geocodificare. Ritorna None se manca l'indirizzo."""
    ind = (indirizzo or "").strip()
    cit = (citta or "").strip()
    if not ind:
        return None
    # togli "Italy"/"Italia"/"IT" finale: lo riaggiungiamo noi in modo uniforme
    ind = re.sub(r"[,\s]+(Italy|Italia|IT)\s*$", "", ind, flags=re.I).strip(" ,")
    parts = [ind]
    if cit and cit.lower() not in ind.lower():
        parts.append(cit)
    return ", ".join(parts) + ", Italia"


def _wait_turn():
    global _last_call
    with _throttle_lock:
        gap = _MIN_INTERVAL.get(PROVIDER, 1.1)
        wait = _last_call + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (429, 500, 502, 503, 504):
            raise GeocodeTemporaryError(f"Il servizio ha risposto {e.code}")
        if e.code in (401, 403):
            raise GeocodeTemporaryError(f"Accesso negato dal servizio ({e.code}): controlla chiave e condizioni d'uso")
        raise GeocodeTemporaryError(f"Errore HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise GeocodeTemporaryError(f"Servizio non raggiungibile: {e}")
    except ValueError:
        raise GeocodeTemporaryError("Risposta non valida dal servizio")


def _dentro_italia(lat, lng):
    return ITALIA_LAT[0] <= lat <= ITALIA_LAT[1] and ITALIA_LNG[0] <= lng <= ITALIA_LNG[1]


def _nominatim(q):
    params = urllib.parse.urlencode({
        "q": q, "format": "jsonv2", "limit": 1, "countrycodes": "it", "addressdetails": 1,
    })
    data = _get_json("https://nominatim.openstreetmap.org/search?" + params)
    if not data:
        return None
    r = data[0]
    lat, lng = float(r["lat"]), float(r["lon"])
    preciso = bool((r.get("address") or {}).get("house_number"))
    return lat, lng, ("ok" if preciso else "approx")


def _geoapify(q):
    if not GEOAPIFY_KEY:
        raise GeocodeTemporaryError("GEOAPIFY_KEY non impostata")
    params = urllib.parse.urlencode({
        "text": q, "format": "json", "limit": 1, "filter": "countrycode:it", "apiKey": GEOAPIFY_KEY,
    })
    data = _get_json("https://api.geoapify.com/v1/geocode/search?" + params)
    risultati = (data or {}).get("results") or []
    if not risultati:
        return None
    r = risultati[0]
    lat, lng = float(r["lat"]), float(r["lon"])
    preciso = bool(r.get("housenumber")) or r.get("result_type") in ("building", "amenity")
    return lat, lng, ("ok" if preciso else "approx")


def geocode(q):
    """
    Ritorna (lat, lng, precisione) con precisione "ok" (numero civico trovato)
    o "approx" (solo via/zona), oppure None se l'indirizzo non e' stato trovato.
    Solleva GeocodeTemporaryError per problemi temporanei (non vanno salvati
    come "non trovato").
    """
    if not q:
        return None
    _wait_turn()
    ris = _geoapify(q) if PROVIDER == "geoapify" else _nominatim(q)
    if ris is None:
        return None
    lat, lng, prec = ris
    if not _dentro_italia(lat, lng):
        return None
    return lat, lng, prec
