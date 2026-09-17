import base64
import csv
import io
import os
import secrets
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from models import Lead, StoricoStato, DEFAULT_STATI, init_db, get_db
import gcal

app = FastAPI(title="CRM Lead")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


# ---------- Autenticazione (Basic Auth, un utente per operatore) ----------
# Configurata tramite variabile d'ambiente AUTH_USERS, formato:
#   "giacomo:PasswordSicura1,mario:PasswordSicura2"
# Se AUTH_USERS non è impostata, l'app resta aperta (comodo per lo sviluppo
# in locale, MA da impostare sempre prima di mettere l'app online).
def _parse_auth_users():
    raw = os.environ.get("AUTH_USERS", "").strip()
    users = {}
    if not raw:
        return users
    for pair in raw.split(","):
        if ":" not in pair:
            continue
        user, pwd = pair.split(":", 1)
        user, pwd = user.strip(), pwd.strip()
        if user and pwd:
            users[user] = pwd
    return users


AUTH_USERS = _parse_auth_users()


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not AUTH_USERS:
            request.state.operatore = None
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        username = None
        if auth_header and auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                user, _, pwd = decoded.partition(":")
                expected = AUTH_USERS.get(user)
                if expected and secrets.compare_digest(pwd, expected):
                    username = user
            except Exception:
                username = None

        if not username:
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="CRM Lead"'},
            )

        request.state.operatore = username
        return await call_next(request)


if AUTH_USERS:
    app.add_middleware(BasicAuthMiddleware)


@app.get("/api/me")
def me(request: Request):
    return {"operatore": getattr(request.state, "operatore", None)}


# ---------- Schemi ----------

class LeadUpdate(BaseModel):
    nome: Optional[str] = None
    cognome: Optional[str] = None
    cellulare: Optional[str] = None
    email: Optional[str] = None
    tipologia: Optional[str] = None
    stato: Optional[str] = None
    citta: Optional[str] = None
    indirizzo: Optional[str] = None
    sorgente: Optional[str] = None
    operatore: Optional[str] = None
    note: Optional[str] = None
    data_recall: Optional[datetime] = None
    operatore_modifica: Optional[str] = None  # chi fa la modifica (per lo storico)


class LeadCreate(BaseModel):
    nome: Optional[str] = None
    cognome: Optional[str] = None
    cellulare: Optional[str] = None
    email: Optional[str] = None
    tipologia: Optional[str] = None
    stato: Optional[str] = "Nuovo"
    citta: Optional[str] = None
    indirizzo: Optional[str] = None
    sorgente: Optional[str] = None
    operatore: Optional[str] = None
    note: Optional[str] = None


def lead_to_dict(l: Lead):
    return {
        "id": l.id,
        "annuncio": l.annuncio,
        "nome": l.nome,
        "cognome": l.cognome,
        "cellulare": l.cellulare,
        "email": l.email,
        "tipologia": l.tipologia,
        "stato": l.stato,
        "citta": l.citta,
        "indirizzo": l.indirizzo,
        "sorgente": l.sorgente,
        "operatore": l.operatore,
        "note": l.note,
        "data_creazione": l.data_creazione.isoformat() if l.data_creazione else None,
        "ultima_modifica": l.ultima_modifica.isoformat() if l.ultima_modifica else None,
        "data_recall": l.data_recall.isoformat() if l.data_recall else None,
        "referente_front_office": l.referente_front_office,
        "id_immobile": l.id_immobile,
        "tipologia_appuntamento": l.tipologia_appuntamento,
        "appuntamento_inizio": l.appuntamento_inizio.isoformat() if l.appuntamento_inizio else None,
        "appuntamento_fine": l.appuntamento_fine.isoformat() if l.appuntamento_fine else None,
        "appuntamento_confermato": l.appuntamento_confermato,
        "google_calendar_configurato": gcal.is_configured(),
    }


# ---------- Endpoint ----------

@app.get("/api/stati")
def get_stati(db: Session = Depends(get_db)):
    """Stati di default + eventuali stati custom già usati nel DB."""
    custom = [r[0] for r in db.query(Lead.stato).distinct().all() if r[0]]
    stati = list(dict.fromkeys(DEFAULT_STATI + custom))  # dedup mantenendo ordine
    return {"stati": stati}


@app.get("/api/leads")
def list_leads(
    search: Optional[str] = None,
    campo: Optional[str] = Query(None, description="nome|cognome|cellulare|email|citta (default: tutti)"),
    tipologia: Optional[str] = None,
    stato: Optional[str] = None,
    citta: Optional[str] = None,
    operatore: Optional[str] = None,
    sorgente: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    order_by: str = "data_creazione",
    order_dir: str = "desc",
    db: Session = Depends(get_db),
):
    q = db.query(Lead)

    if search:
        like = f"%{search}%"
        if campo and hasattr(Lead, campo):
            q = q.filter(getattr(Lead, campo).ilike(like))
        else:
            q = q.filter(or_(
                Lead.nome.ilike(like),
                Lead.cognome.ilike(like),
                Lead.cellulare.ilike(like),
                Lead.email.ilike(like),
                Lead.citta.ilike(like),
                Lead.indirizzo.ilike(like),
            ))

    if tipologia:
        q = q.filter(Lead.tipologia == tipologia)
    if stato:
        q = q.filter(Lead.stato == stato)
    if citta:
        q = q.filter(Lead.citta.ilike(f"%{citta}%"))
    if operatore:
        q = q.filter(Lead.operatore == operatore)
    if sorgente:
        q = q.filter(Lead.sorgente == sorgente)

    total = q.count()

    order_col = getattr(Lead, order_by, Lead.data_creazione)
    order_col = order_col.desc() if order_dir == "desc" else order_col.asc()
    q = q.order_by(order_col)

    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    leads = q.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "results": [lead_to_dict(l) for l in leads],
    }


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).get(lead_id)
    if not lead:
        raise HTTPException(404, "Lead non trovato")
    storico = (
        db.query(StoricoStato)
        .filter(StoricoStato.lead_id == lead_id)
        .order_by(StoricoStato.data.desc())
        .all()
    )
    d = lead_to_dict(lead)
    d["storico"] = [
        {
            "stato_precedente": s.stato_precedente,
            "stato_nuovo": s.stato_nuovo,
            "operatore": s.operatore,
            "nota": s.nota,
            "data": s.data.isoformat() if s.data else None,
        }
        for s in storico
    ]
    return d


@app.post("/api/leads")
def create_lead(payload: LeadCreate, db: Session = Depends(get_db)):
    lead = Lead(**payload.dict())
    db.add(lead)
    db.commit()
    db.refresh(lead)
    db.add(StoricoStato(lead_id=lead.id, stato_precedente=None, stato_nuovo=lead.stato, operatore=lead.operatore))
    db.commit()
    return lead_to_dict(lead)


@app.patch("/api/leads/{lead_id}")
def update_lead(lead_id: int, payload: LeadUpdate, db: Session = Depends(get_db)):
    lead = db.query(Lead).get(lead_id)
    if not lead:
        raise HTTPException(404, "Lead non trovato")

    data = payload.dict(exclude_unset=True)
    operatore_modifica = data.pop("operatore_modifica", None)

    stato_precedente = lead.stato
    for k, v in data.items():
        setattr(lead, k, v)
    lead.ultima_modifica = datetime.utcnow()

    if "stato" in data and data["stato"] != stato_precedente:
        db.add(StoricoStato(
            lead_id=lead.id,
            stato_precedente=stato_precedente,
            stato_nuovo=data["stato"],
            operatore=operatore_modifica or lead.operatore,
        ))

    db.commit()
    db.refresh(lead)
    return lead_to_dict(lead)


@app.delete("/api/leads/{lead_id}")
def delete_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).get(lead_id)
    if not lead:
        raise HTTPException(404, "Lead non trovato")
    if lead.google_event_id:
        gcal.delete_event(lead.google_event_id)
    db.delete(lead)
    db.commit()
    return {"ok": True}


class AppuntamentoIn(BaseModel):
    appuntamento_inizio: datetime
    appuntamento_fine: datetime
    referente_front_office: Optional[str] = None
    id_immobile: Optional[str] = None
    tipologia_appuntamento: Optional[str] = "Standard"
    appuntamento_confermato: Optional[str] = "Non confermato"
    operatore_modifica: Optional[str] = None


@app.post("/api/leads/{lead_id}/appuntamento")
def set_appuntamento(lead_id: int, payload: AppuntamentoIn, db: Session = Depends(get_db)):
    lead = db.query(Lead).get(lead_id)
    if not lead:
        raise HTTPException(404, "Lead non trovato")

    data = payload.dict()
    operatore_modifica = data.pop("operatore_modifica", None)
    for k, v in data.items():
        setattr(lead, k, v)
    lead.ultima_modifica = datetime.utcnow()
    db.commit()
    db.refresh(lead)

    calendar_error = None
    if gcal.is_configured():
        try:
            event_id = gcal.upsert_event(lead, lead.google_event_id)
            if event_id:
                lead.google_event_id = event_id
                db.commit()
                db.refresh(lead)
        except Exception as e:
            calendar_error = str(e)

    result = lead_to_dict(lead)
    if calendar_error:
        result["calendar_sync_error"] = calendar_error
    return result


@app.delete("/api/leads/{lead_id}/appuntamento")
def delete_appuntamento(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).get(lead_id)
    if not lead:
        raise HTTPException(404, "Lead non trovato")
    if lead.google_event_id:
        gcal.delete_event(lead.google_event_id)
    lead.appuntamento_inizio = None
    lead.appuntamento_fine = None
    lead.google_event_id = None
    lead.appuntamento_confermato = None
    db.commit()
    return {"ok": True}


@app.get("/api/stats")
def stats(db: Session = Depends(get_db)):
    per_stato = db.query(Lead.stato, func.count(Lead.id)).group_by(Lead.stato).all()
    per_tipologia = db.query(Lead.tipologia, func.count(Lead.id)).group_by(Lead.tipologia).all()
    per_operatore = db.query(Lead.operatore, func.count(Lead.id)).group_by(Lead.operatore).all()
    totale = db.query(func.count(Lead.id)).scalar()
    return {
        "totale": totale,
        "per_stato": {k or "N/D": v for k, v in per_stato},
        "per_tipologia": {k or "N/D": v for k, v in per_tipologia},
        "per_operatore": {k or "N/D": v for k, v in per_operatore},
    }


@app.get("/api/filtri")
def filtri(db: Session = Depends(get_db)):
    """Valori distinti per popolare le tendine dei filtri."""
    def distinct(col):
        return sorted([r[0] for r in db.query(col).distinct().all() if r[0]])
    return {
        "citta": distinct(Lead.citta),
        "operatore": distinct(Lead.operatore),
        "sorgente": distinct(Lead.sorgente),
        "tipologia": distinct(Lead.tipologia),
    }


# Mappa colonne CSV (come da export Vicidial/gestionale) -> campi del modello
CSV_COLUMN_MAP = {
    "annunci": "annuncio",
    "nome": "nome",
    "cognome": "cognome",
    "cellulare": "cellulare",
    "email": "email",
    "tipologia": "tipologia",
    "esito": "stato",
    "città": "citta",
    "citta": "citta",
    "indirizzo": "indirizzo",
    "sorgente": "sorgente",
    "operatore": "operatore",
    "data creazione": "data_creazione",
    "ultima modifica": "ultima_modifica",
    "data recall": "data_recall",
}


def parse_data_it(s: str):
    if not s or not s.strip():
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


@app.post("/api/import")
async def import_csv(
    file: UploadFile = File(...),
    aggiorna_esistenti: bool = Query(False, description="Se true, aggiorna i lead già presenti (match su cellulare+email)"),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    creati, aggiornati, saltati = 0, 0, 0

    for row in reader:
        norm = {}
        for k, v in row.items():
            if k is None:
                continue
            key = CSV_COLUMN_MAP.get(k.strip().lower())
            if key:
                norm[key] = v.strip() if isinstance(v, str) else v

        cellulare = norm.get("cellulare") or None
        email = norm.get("email") or None

        existing = None
        if cellulare or email:
            q = db.query(Lead)
            if cellulare:
                q = q.filter(Lead.cellulare == cellulare)
            elif email:
                q = q.filter(Lead.email == email)
            existing = q.first()

        if existing and not aggiorna_esistenti:
            saltati += 1
            continue

        data_creazione = parse_data_it(norm.get("data_creazione")) or datetime.utcnow()
        data_recall = parse_data_it(norm.get("data_recall"))

        if existing:
            existing.nome = norm.get("nome") or existing.nome
            existing.cognome = norm.get("cognome") or existing.cognome
            existing.email = email or existing.email
            existing.tipologia = norm.get("tipologia") or existing.tipologia
            existing.stato = norm.get("stato") or existing.stato
            existing.citta = norm.get("citta") or existing.citta
            existing.indirizzo = norm.get("indirizzo") or existing.indirizzo
            existing.sorgente = norm.get("sorgente") or existing.sorgente
            existing.operatore = norm.get("operatore") or existing.operatore
            existing.data_recall = data_recall or existing.data_recall
            existing.ultima_modifica = datetime.utcnow()
            aggiornati += 1
        else:
            lead = Lead(
                annuncio=norm.get("annuncio"),
                nome=norm.get("nome"),
                cognome=norm.get("cognome"),
                cellulare=cellulare,
                email=email,
                tipologia=norm.get("tipologia"),
                stato=norm.get("stato") or "Nuovo",
                citta=norm.get("citta"),
                indirizzo=norm.get("indirizzo"),
                sorgente=norm.get("sorgente"),
                operatore=norm.get("operatore"),
                data_creazione=data_creazione,
                data_recall=data_recall,
            )
            db.add(lead)
            creati += 1

    db.commit()
    return {"creati": creati, "aggiornati": aggiornati, "saltati": saltati}


# ---------- Frontend (unico file HTML, nessun asset separato) ----------
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
INDEX_PATH = os.path.join(FRONTEND_DIR, "index.html")

if os.path.isfile(INDEX_PATH):
    @app.get("/")
    def index():
        return FileResponse(INDEX_PATH)
