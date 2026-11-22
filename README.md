# 🍷 Catawiki Wine Monitor ("Cantina Radar")

Monitora le aste di vino, Champagne e vini dolci su Catawiki e ti segnala, su **Telegram** e su una **dashboard web**, i lotti il cui costo reale è nettamente sotto il valore di mercato.

- **Gratis**: gira su GitHub Actions (nessun server). La dashboard è pubblicata su GitHub Pages.
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

## Installazione (circa 20 minuti, una volta sola)

### 1. Crea il bot Telegram
1. Su Telegram apri **@BotFather**, invia `/newbot`, scegli un nome. Ricevi un **token** (tipo `123456:ABC...`).
2. Apri il tuo nuovo bot e premi **Avvia** (o scrivigli un messaggio qualsiasi).
3. Apri **@userinfobot**: ti risponde con il tuo **ID** numerico. Questo è il `TELEGRAM_CHAT_ID`.

### 2. Metti il progetto su GitHub
1. Crea un account gratuito su [github.com](https://github.com) se non ce l'hai.
2. **New repository** → nome per esempio `cantina-radar` → **Public** → *Create repository*.
   *Pubblico* significa minuti di Actions illimitati e Pages gratuito. Nel repository ci sono solo il codice e dati pubblici di Catawiki. Il token Telegram resta segreto (vedi passo 3).
3. Nella pagina del repository: **Add file → Upload files** e trascina **tutto il contenuto** della cartella del progetto, compresa la cartella nascosta `.github`. Su Mac, nel Finder premi `Cmd+Shift+.` per vedere i file nascosti. Poi *Commit changes*.
   - In alternativa usa [GitHub Desktop](https://desktop.github.com/).

### 3. Inserisci i segreti
**Settings → Secrets and variables → Actions → New repository secret**, due volte:
- `TELEGRAM_BOT_TOKEN` = il token di BotFather
- `TELEGRAM_CHAT_ID` = il tuo ID

### 4. Attiva la dashboard
**Settings → Pages → Build and deployment → Source: GitHub Actions**.

### 5. Primo avvio
**Actions** → *Monitor aste vino* → **Run workflow**. Dopo 2–5 minuti:
- la dashboard è su `https://<tuo-utente>.github.io/cantina-radar/`
- su Telegram scrivi `/aiuto` al bot (la risposta arriva al ciclo successivo, vedi sotto).

Da qui in poi gira da solo ogni 30 minuti, dalle 7:00 alle 23:30.

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

Su GitHub Actions i comandi vengono letti a ogni ciclo, quindi **la risposta arriva entro circa 30 minuti**. Se tieni l'app accesa sul PC (`python -m cwmon bot`) risponde subito. Il bot accetta comandi solo dalla tua chat.

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
python -m cwmon run           # un ciclo completo
python -m cwmon loop -m 15    # ciclo ogni 15 minuti, finché il PC resta acceso
python -m cwmon serve         # apre la dashboard su http://localhost:8000
python -m cwmon bot           # bot con risposte immediate
python -m pytest              # test automatici
```

---

## Limiti da conoscere

- **Catawiki non ha un'API pubblica.** L'app legge le pagine pubbliche di categoria e l'endpoint che il sito usa per le offerte live: poche richieste, distanziate di 2 secondi. Se Catawiki cambia struttura, la lettura può smettere di funzionare. Lancia `python -m cwmon doctor`: salva in `debug/` i campioni grezzi utili per sistemare il parser.
- **Il servizio potrebbe bloccare gli IP di GitHub.** Se `doctor` funziona dal tuo PC ma i cicli su Actions non trovano lotti, usa la modalità locale (`loop`).
- **Gli avvisi sono indicativi.** Verifica sempre livello del vino, condizioni di conservazione, spedizione reale e dazi (i venditori extra-UE possono comportare IVA all'importazione).
- **L'ultimo minuto conta.** Molte offerte arrivano negli ultimi minuti: lo sconto a 3 ore dalla chiusura tende a ridursi. Per questo l'app ti dà l'**offerta massima**, non solo lo sconto attuale.
- GitHub sospende i workflow programmati dopo 60 giorni senza attività nel repository. In quel caso basta rientrare in **Actions** e riattivarlo.
- I cicli di GitHub Actions possono partire con 5–15 minuti di ritardo nelle ore di punta.

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
.github/workflows/monitor.yml   esecuzione automatica gratuita
```
