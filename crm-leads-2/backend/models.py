import os
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Text, ForeignKey, Index,
    Float, Boolean, text,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./crm.db")

# Railway/Heroku-style postgres URLs sometimes come as postgres:// — SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Stati di default della pipeline (personalizzabili dal frontend/DB in futuro)
DEFAULT_STATI = [
    "Nuovo",
    "Pending",
    "Contattato",
    "Potential buyer / tenant",
    "In gestione agenti",
    "Appuntamento fissato",
    "Incarico di vendita",
    "Vendita conclusa",
    "Out of zone",
    "Non interessato",
    "Non risponde",
    "Numero errato",
]


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    annuncio = Column(String(64), nullable=True)  # id annuncio collegato, se presente
    nome = Column(String(128), nullable=True, index=True)
    cognome = Column(String(128), nullable=True, index=True)
    cellulare = Column(String(64), nullable=True, index=True)
    email = Column(String(256), nullable=True, index=True)
    tipologia = Column(String(32), nullable=True, index=True)  # Buyer / Seller
    stato = Column(String(64), nullable=False, default="Nuovo", index=True)
    citta = Column(String(128), nullable=True, index=True)
    indirizzo = Column(String(256), nullable=True)
    sorgente = Column(String(128), nullable=True, index=True)
    operatore = Column(String(128), nullable=True, index=True)
    note = Column(Text, nullable=True)
    data_creazione = Column(DateTime, default=datetime.utcnow, index=True)
    ultima_modifica = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    data_recall = Column(DateTime, nullable=True, index=True)

    # Appuntamento di acquisizione (opzionale, sincronizzato su Google Calendar)
    referente_front_office = Column(String(128), nullable=True)
    id_immobile = Column(String(64), nullable=True)
    tipologia_appuntamento = Column(String(64), nullable=True)
    appuntamento_inizio = Column(DateTime, nullable=True, index=True)
    appuntamento_fine = Column(DateTime, nullable=True)
    appuntamento_confermato = Column(String(32), nullable=True, default="Non confermato")
    google_event_id = Column(String(256), nullable=True)

    # Posizione sulla mappa (calcolata dal geocoding dell'indirizzo).
    # geo_status: da_fare | ok (civico trovato) | approx (solo via/zona)
    #             | non_trovato | senza_indirizzo
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    geo_status = Column(String(32), nullable=True, default="da_fare", server_default="da_fare")

    # Consensi al marketing: partono sempre a False, vanno spuntati a mano
    # solo quando il contatto ha dato un consenso esplicito.
    consenso_email = Column(Boolean, nullable=True, default=False, server_default=text("false"))
    consenso_sms = Column(Boolean, nullable=True, default=False, server_default=text("false"))

    storico = relationship("StoricoStato", back_populates="lead", cascade="all, delete-orphan")


class StoricoStato(Base):
    __tablename__ = "storico_stato"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    stato_precedente = Column(String(64), nullable=True)
    stato_nuovo = Column(String(64), nullable=False)
    operatore = Column(String(128), nullable=True)
    nota = Column(Text, nullable=True)
    data = Column(DateTime, default=datetime.utcnow, index=True)

    lead = relationship("Lead", back_populates="storico")


Index("ix_leads_cellulare_email", Lead.cellulare, Lead.email)
# Gli indici sulle coordinate esistono gia' nel database (creati a mano su Neon)
Index("idx_leads_geo", Lead.lat, Lead.lng)
Index("idx_leads_geo_status", Lead.geo_status)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
