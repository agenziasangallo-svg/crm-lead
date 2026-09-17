# CRM Lead — Properties Finding

App web condivisa per gestire i lead (buyer/seller) dalla ricerca fino
all'incarico di vendita. Backend FastAPI + Postgres, frontend in un
unico HTML (nessuna build necessaria).

## Cosa fa

- Ricerca full-text su nome, cognome, cellulare, email, città, indirizzo
- Filtri per tipologia, stato pipeline, città, operatore, sorgente
- Scheda lead con modifica campi, cambio stato pipeline e **storico
  completo dei passaggi di stato** (chi, quando, da → a)
- Import CSV dagli export del vostro tool (Vicidial/altro): riconosce le
  colonne Annunci, Nome, Cognome, Cellulare, Email, Tipologia, Esito,
  Città, Indirizzo, Sorgente, Operatore, Data creazione, Ultima
  modifica, Data recall. Evita duplicati (match su cellulare/email) o li
  aggiorna, a scelta.
- Dashboard statistiche: conteggio lead per stato, tipologia, operatore
- Pipeline di default (modificabile, vedi sotto):
  Nuovo → Pending → Contattato → Potential buyer/tenant → In gestione
  agenti → Appuntamento fissato → **Incarico di vendita** / Vendita
  conclusa, oltre agli stati di chiusura negativa (Out of zone, Non
  interessato, Non risponde, Numero errato)

Lo stato è un campo libero: se scrivi/importi un valore diverso da
quelli di default, l'app lo aggiunge automaticamente alle scelte
disponibili (utile perché il vostro export ha già altri "Esito" in uso).

## Deploy su Railway (consigliato, stesso posto dell'Agente Homebetter)

1. Crea un nuovo progetto su Railway, collega questa cartella come repo
   (o carica lo zip / fai push su un repo GitHub dedicato)
2. Aggiungi un plugin **PostgreSQL** al progetto: Railway crea da solo
   la variabile d'ambiente `DATABASE_URL` e il backend la userà in
   automatico (vedi `backend/models.py`)
3. Imposta il **Root Directory** del servizio web su `backend`
4. Railway rileva `requirements.txt` e `Procfile` e fa il deploy da solo
5. Aprendo l'URL del servizio vedrai direttamente l'interfaccia (il
   backend serve anche il frontend da `/`)

Se preferite girare in locale prima del deploy:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
# apri http://localhost:8000
```
Senza `DATABASE_URL` impostata usa SQLite in locale (`crm.db`), utile
per test veloci prima di collegare Postgres.

## Importare i vostri 595.800 lead

1. Esportate il CSV dal vostro gestionale/Vicidial (le colonne della
   tabella che mi hai incollato vanno bene così come sono)
2. Nell'app, pulsante **"Importa CSV"** in alto → carica il file
3. Per un export così grande, se il file è molto pesante (decine di MB)
   conviene dividerlo in più CSV più piccoli e importarli uno dopo
   l'altro — l'endpoint di import non ha limiti di numero di lead
   (a differenza degli strumenti "artifact" di Claude, che si fermano a
   5.000 record: per questo l'app è un servizio a sé, non una pagina
   Claude)

## Accesso protetto (login per operatore)

L'app ora richiede autenticazione — obbligatoria se la metti online,
visto che i lead contengono dati personali. Si configura con **una
sola variabile d'ambiente** su Railway, `AUTH_USERS`, formato:

```
giacomo:PasswordSicura1,mario:PasswordSicura2
```

(niente spazi attorno ai `:`/`,`; scegli password vere, non questi
esempi). Ogni operatore entra con il proprio utente/password — il
browser chiede le credenziali una volta e le ricorda. Il nome
utente inserito diventa automaticamente il valore "operatore" mostrato
nell'app e registrato nello storico stati: non serve più scriverlo a
mano.

**Senza `AUTH_USERS` impostata l'app resta completamente aperta** —
va bene solo per test in locale, mai per l'uso online. Su Railway:
Settings del servizio → Variables → aggiungi `AUTH_USERS`.

Per aggiungere/togliere un operatore in futuro basta modificare quella
variabile, senza toccare codice. Per uscire (logout) su Basic Auth
bisogna chiudere il browser o cancellare i dati del sito — è un limite
noto di questo tipo di login semplice; se un domani vi serve un vero
logout dal pulsante, si può passare a un sistema a sessioni, ma per due
persone questa soluzione è più che sufficiente.

## Personalizzare la pipeline

Gli stati di default sono in `backend/models.py`, variabile
`DEFAULT_STATI`. Modifica quella lista e rifai il deploy per cambiare
le voci proposte nel menu a tendina (gli stati già usati sui lead
restano comunque visibili anche se li togli da lì).

## Appuntamenti collegati a Google Calendar

Ogni lead può avere un appuntamento (data/ora inizio-fine, tipologia,
referente front-office, ID immobile, stato conferma). Se colleghi
Google Calendar, ogni volta che salvi un appuntamento viene creato o
aggiornato automaticamente un evento sul calendario condiviso
d'ufficio — con indirizzo, telefono, email e tutti i dettagli già
compilati nella descrizione. Se non colleghi nulla, la funzione resta
disponibile ugualmente ma solo dentro l'app (nessun evento su
Calendar).

**Setup (una volta sola), visto che usate Google Workspace aziendale:**

1. Vai su [console.cloud.google.com](https://console.cloud.google.com),
   crea un progetto (o usane uno esistente dell'azienda)
2. In "API e servizi" → "Libreria", cerca e abilita **Google Calendar API**
3. In "API e servizi" → "Credenziali" → "Crea credenziali" → **Account di
   servizio**. Dagli un nome qualsiasi (es. "crm-lead-calendar"), nessun
   ruolo particolare necessario
4. Apri l'account di servizio appena creato → scheda "Chiavi" → "Aggiungi
   chiave" → JSON. Si scarica un file `.json`: tienilo da parte, non va
   condiviso pubblicamente
5. Apri **Google Calendar**, vai sulle impostazioni del calendario
   condiviso d'ufficio → "Condividi con persone specifiche" → aggiungi
   l'indirizzo email dell'account di servizio (è dentro il JSON, campo
   `client_email`, tipo `crm-lead-calendar@tuoprogetto.iam.gserviceaccount.com`)
   con permesso **"Apportare modifiche agli eventi"**
6. Sempre nelle impostazioni di quel calendario, sezione "Integra
   calendario", copia l'**ID calendario**
7. Su Railway, Settings del servizio → Variables, aggiungi:
   - `GOOGLE_SERVICE_ACCOUNT_JSON` → incolla **tutto** il contenuto del
     file JSON scaricato al punto 4 (come testo unico, su una riga o
     multilinea va bene comunque)
   - `GOOGLE_CALENDAR_ID` → l'ID copiato al punto 6

Da quel momento, ogni appuntamento salvato nell'app compare sul
calendario ufficio in automatico. Se l'evento viene cancellato a mano
da Calendar, il prossimo salvataggio nell'app ne ricrea uno nuovo
senza errori.

**Nota sul database esistente**: se hai già fatto il primo deploy
prima di questa funzione, il database ha bisogno delle nuove colonne
per gli appuntamenti. Se il tuo Postgres è ancora vuoto/di test, la
via più semplice è cancellare e ricreare il database su Railway (si
rigenera da solo all'avvio). Se invece contiene già lead veri che non
vuoi perdere, fammelo sapere e ti preparo la query SQL di migrazione
invece di ripartire da zero.
