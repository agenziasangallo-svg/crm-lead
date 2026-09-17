"""
Sincronizzazione appuntamenti con Google Calendar (calendario condiviso
d'ufficio), tramite Service Account.

Setup richiesto (una volta sola), vedi anche README.md:
1. Su console.cloud.google.com crea un progetto e abilita "Google Calendar API".
2. Crea una Service Account, genera una chiave JSON.
3. Sul calendario Google condiviso d'ufficio, in "Impostazioni e condivisione",
   condividilo con l'email della service account (tipo xxx@progetto.iam.gserviceaccount.com),
   permesso "Apportare modifiche agli eventi".
4. Imposta le variabili d'ambiente:
   - GOOGLE_SERVICE_ACCOUNT_JSON: contenuto completo del file JSON della chiave
   - GOOGLE_CALENDAR_ID: id del calendario (in Impostazioni calendario, sotto
     "Integra calendario" — spesso è un indirizzo email o una stringa lunga)

Se queste variabili non sono impostate, la sincronizzazione è semplicemente
disattivata (il resto dell'app continua a funzionare normalmente).
"""
import json
import os

CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID")
_CREDS_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

SCOPES = ["https://www.googleapis.com/auth/calendar"]

_service = None
_service_init_tried = False


def _get_service():
    global _service, _service_init_tried
    if _service is not None:
        return _service
    if _service_init_tried:
        return None
    _service_init_tried = True

    if not _CREDS_JSON or not CALENDAR_ID:
        return None

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = json.loads(_CREDS_JSON)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _service


def is_configured():
    return bool(_CREDS_JSON and CALENDAR_ID)


def upsert_event(lead, event_id=None):
    """Crea o aggiorna l'evento calendario per un lead. Ritorna l'id evento."""
    service = _get_service()
    if not service:
        return None
    if not lead.appuntamento_inizio or not lead.appuntamento_fine:
        return None

    nome_completo = f"{lead.nome or ''} {lead.cognome or ''}".strip() or "Lead"
    tipo = lead.tipologia_appuntamento or "Standard"
    summary = f"Appuntamento {tipo} - {nome_completo}"
    if lead.appuntamento_confermato and lead.appuntamento_confermato != "Confermato":
        summary += " | Non Confermato"

    description = "\n".join([
        f"Telefono: {lead.cellulare or '-'}",
        f"Email: {lead.email or '-'}",
        f"Referente front-office: {lead.referente_front_office or '-'}",
        f"ID immobile: {lead.id_immobile or '-'}",
        f"Tipologia appuntamento: {tipo}",
        f"Stato: {lead.appuntamento_confermato or 'Non confermato'}",
    ])

    body = {
        "summary": summary,
        "location": lead.indirizzo or lead.citta or "",
        "description": description,
        "start": {"dateTime": lead.appuntamento_inizio.isoformat(), "timeZone": "Europe/Rome"},
        "end": {"dateTime": lead.appuntamento_fine.isoformat(), "timeZone": "Europe/Rome"},
    }

    if event_id:
        try:
            ev = service.events().update(calendarId=CALENDAR_ID, eventId=event_id, body=body).execute()
            return ev.get("id")
        except Exception:
            # l'evento potrebbe essere stato cancellato manualmente dal calendario: ne creo uno nuovo
            pass

    ev = service.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    return ev.get("id")


def delete_event(event_id):
    service = _get_service()
    if not service or not event_id:
        return
    try:
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
    except Exception:
        pass
