# 🍷 Catawiki Wine Monitor ("Cantina Radar")

Monitora le aste di vino, Champagne e vini dolci su Catawiki e ti segnala, su **Telegram** e su una **dashboard web**, i lotti il cui costo reale è nettamente sotto il valore di mercato.

- **Gratis**: gira sul tuo PC. Catawiki blocca le richieste dai server cloud come GitHub Actions (errore 403), quindi la raccolta deve partire dalla tua connessione di casa.
- **Costo reale**: offerta + commissione Catawiki (9% + 3 €) + spedizione stimata, diviso per bottiglie equivalenti da 0,75 L (una magnum vale 2).
- **Offerta massima consigliata**: per ogni lotto ti dice fino a quanto puoi offrire restando sopra il tuo sconto minimo.
- **Uso esclusivamente personale.**

---

## Come stima il valore di mercato

| Fonte | Affidabilità | Come funziona |
|---|---|---|
| `riferimenti.csv` | alta (90%) | I prezzi che inserisci tu, per bottiglia (da Wine-Searcher, Vivino, la tua enoteca…) |
| Storico stessa annata | 45–85% | Prezzi finali delle aste Catawiki chiuse, registrati automaticamente dall'app. Più vendite = più affidabile |
| Stima dell'esperto | 60% | La forchetta che Catawiki mostra sulla pagina del lotto (quando c'è) |
| Storico altre annate | 35% | Stesso vino, annate diverse: mostrato in dashboard ma sotto la soglia degli avvisi |

Se ci sono più fonti, il valore è una media pesata sull'affidabilità. Quando le fonti concordano l'affidabilità sale, quando divergono scende.

> **All'inizio lo storico è vuoto.** Nelle prime settimane gli avvisi arrivano soprattutto dai vini che hai messo in `riferimenti.csv` e dalle stime degli esperti. Lo storico cresce da solo a ogni asta chiusa: dopo un mese copre già molti vini ricorrenti.

### Il file `riferimenti.csv`

```csv
vino,annata,prezzo_bottiglia,fonte,note
Tenuta San Guido Sassicaia Bolgheri,2015,330,wine-searcher,
Bollinger Special Cuvée Champagne,,55,vivino,annata vuota = qualunque annata/NV
```

- **I prezzi già presenti sono solo esempi**: sostituiscili con i tuoi.
- Il nome viene confrontato in modo "elastico" (accenti, maiuscole, "Château", "Domaine"… non contano). Scrivi produttore + vino + denominazione. Un nome troppo generico come "Barolo" verrebbe abbinato a tutti i Barolo.
- Il prezzo è **per bottiglia da 0,75 L**, IVA inclusa, spedizione esclusa.

---

## Installazione sul PC (10 minuti, una volta sola)

### 1. Crea il bot Telegram
1. Su Telegram cerca **@BotFather**, invia `/newbot`, scegli un nome e uno username che finisca con `bot`. Ricevi un **token** (tipo `7123456789:AAH...`).
2. Apri il link del tuo nuovo bot e premi **Avvia**.
3. Cerca **@userinfobot** e premi **Avvia**: ti risponde con il tuo **Id** numerico.

### 2. Installa Python (se non ce l'hai)
Scaricalo da [python.org/downloads](https://www.python.org/downloads/). Su Windows, durante l'installazione spunta **"Add python.exe to PATH"**.

### 3. Scarica il progetto
Sulla pagina del repository: **Code → Download ZIP**, poi estrai la cartella dove preferisci (per esempio in Documenti).

### 4. Avvia con un doppio clic
- **Windows:** `avvia-windows.bat`. Se compare l'avviso "PC protetto da Windows", clicca *Ulteriori informazioni → Esegui comunque*.
- **Mac:** apri il Terminale, scrivi `bash ` (con lo spazio), trascina dentro il file `avvia-mac.command` e premi Invio. Dalle volte successive basta il doppio clic sul file.

La prima volta lo script installa tutto e apre il file `.env`. Lì scrivi il token e il tuo Id al posto degli esempi, salva e chiudi:
```
TELEGRAM_BOT_TOKEN=7123456789:AAH...
TELEGRAM_CHAT_ID=6513444198
```
Poi si apre la dashboard nel browser e parte il monitoraggio, che si ripete ogni 20 minuti. **Lascia aperta la finestra nera**: finché è aperta ricevi gli avvisi, e il bot risponde subito ai comandi. Lo script mostra anche un indirizzo `http://192.168.x.x:8000/` per aprire la dashboard dal telefono, se è sulla stessa Wi-Fi.

> Il PC deve restare acceso e non andare in stop. Il Mac viene tenuto sveglio in automatico. Su Windows controlla *Impostazioni → Sistema → Alimentazione → Sospensione: Mai* (almeno quando è collegato alla corrente). Per un monitoraggio sempre acceso, va benissimo un vecchio portatile o un Raspberry Pi.

### Primo controllo
Se non arrivano lotti, apri un terminale nella cartella ed esegui `.venv\Scripts\python -m cwmon doctor` (Windows) oppure `.venv/bin/python -m cwmon doctor` (Mac). Ti dice quale passaggio non funziona e salva dei campioni in `debug/`.

### E GitHub?
Il repository resta il posto dove si trova il codice: ogni aggiornamento lo trovi lì. L'esecuzione automatica su GitHub Actions è disattivata perché Catawiki la blocca.

---

## Comandi del bot Telegram

| Comando | Effetto |
|---|---|
| `/top` | Migliori occasioni aperte ora |
| `/stato` | Statistiche e impostazioni attive |
| `/soglia 30` | Sconto minimo per gli avvisi (30%) |
| `/budget 200` | Ignora lotti con offerta oltre 200 € (`/budget 0` = nessun limite) |
| `/ore 3` | Avvisa per lotti che chiudono entro 3 ore |
| `/pausa` · `/riprendi` | Sospende/riattiva gli avvisi |

Con l'app avviata sul PC il bot risponde subito. Accetta comandi solo dalla tua chat.

Ogni lotto genera al massimo due avvisi: il primo quando entra nella finestra di chiusura, e un'**ultima chiamata** negli ultimi 45 minuti se è ancora conveniente.

---

## Configurazione (`config.yaml`)

I parametri principali (sono tutti commentati nel file):
- `categories`: 443 Vino, 961 Champagne, 971 Porto e vini dolci (437 Whisky disponibile ma il parser è pensato per il vino)
- `spedizione_lotto`: la spedizione verso di te (default 25 €). Controlla sempre la cifra reale sulla pagina del lotto
- `sconto_minimo`, `ore_alla_chiusura`, `affidabilita_minima`, `budget_massimo`
- `includi` / `escludi`: parole chiave (es. `includi: ["barolo", "brunello", "bordeaux"]`)

---

## Uso sul tuo PC (facoltativo)

Serve Python 3.10 o superiore.

```bash
pip install -r requirements.txt
cp .env.example .env          # inserisci token e chat id
python -m cwmon doctor        # verifica che la lettura di Catawiki funzioni
python -m cwmon demo          # dashboard con dati di esempio in site-demo/index.html
python -m cwmon start         # tutto insieme: monitoraggio + bot + dashboard (quello che usano gli script)
python -m cwmon run           # un ciclo completo
python -m cwmon loop -m 15    # ciclo ogni 15 minuti, finché il PC resta acceso
python -m cwmon serve         # apre la dashboard su http://localhost:8000
python -m cwmon bot           # bot con risposte immediate
python -m pytest              # test automatici
```

---

## Limiti da conoscere

- **Catawiki non ha un'API pubblica.** L'app legge le pagine pubbliche di categoria e l'endpoint che il sito usa per le offerte live: poche richieste, distanziate di 2 secondi. Se Catawiki cambia struttura, la lettura può smettere di funzionare. Lancia `python -m cwmon doctor`: salva in `debug/` i campioni grezzi utili per sistemare il parser.
- **Catawiki blocca le richieste dai server cloud** (GitHub Actions, verificato: HTTP 403). Per questo l'app gira sul PC.
- **Gli avvisi sono indicativi.** Verifica sempre livello del vino, condizioni di conservazione, spedizione reale e dazi (i venditori extra-UE possono comportare IVA all'importazione).
- **L'ultimo minuto conta.** Molte offerte arrivano negli ultimi minuti: lo sconto a 3 ore dalla chiusura tende a ridursi. Per questo l'app ti dà l'**offerta massima**, non solo lo sconto attuale.
- Gli avvisi arrivano solo mentre il PC è acceso e l'app è aperta.

---

## Struttura del progetto

```
cwmon/
  catawiki.py      lettura pagine categoria, offerte live, stima esperto
  parser.py        interpretazione dei titoli (annata, produttore, formato, n. bottiglie)
  valuation.py     valore di mercato, costo reale, offerta massima
  monitor.py       ciclo principale, avvisi, comandi Telegram
  telegram.py      messaggi e bot
  dashboard.py     generazione della dashboard (+ dashboard_template.html)
  db.py            database SQLite (salvato sul branch "data" del repository)
config.yaml        impostazioni
riferimenti.csv    i tuoi prezzi di riferimento
.github/workflows/monitor.yml   esecuzione su GitHub (solo manuale: Catawiki la blocca)
avvia-windows.bat / avvia-mac.command   avvio con doppio clic
```
