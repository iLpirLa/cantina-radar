# 🍷 Catawiki Wine Monitor ("Cantina Radar")

Valuta le aste di vino, Champagne e vini dolci che stai guardando su Catawiki e ti mostra quali hanno un costo reale nettamente sotto il valore di mercato. I risultati arrivano su una **dashboard web** e, per le occasioni, su **Telegram**.

- **Come funziona**: su Catawiki premi il pulsante **🍷 Cantina Radar** nella barra dei preferiti. Il pulsante legge i lotti della pagina che stai guardando (più alcune pagine successive) e le offerte aggiornate, poi li passa all'app sul tuo computer, che li valuta.
- **Perché un pulsante e non un monitoraggio automatico**: Catawiki blocca le richieste che arrivano da programmi (errore 403, verificato sia dai server di GitHub sia da un Mac di casa). Il pulsante lavora dentro il tuo browser, mentre navighi tu, quindi rispetta questo blocco.
- **Gratis**: gira sul tuo computer, senza servizi a pagamento.
- **Costo reale**: offerta + commissione Catawiki (9% + 3 €) + spedizione stimata, diviso per bottiglie equivalenti da 0,75 L (una magnum vale 2).
- **Offerta massima consigliata**: per ogni lotto ti dice fino a quanto puoi offrire restando sopra il tuo sconto minimo.
- **Uso esclusivamente personale.**

---

## La dashboard

- **Il tuo obiettivo** (in alto): sconto minimo che cerchi, punteggio Vivino minimo, offerta massima, finestra per gli avvisi e **paese di spedizione** (Italia o Spagna), con il costo stimato per lotto e per bottiglia. Quando premi **Salva obiettivo**, valgono sia per la dashboard sia per Telegram.
- **Filtri**: ricerca libera, **tipologia** (rosso, bianco, rosato, spumante, dolce e fortificato: ricavata dal titolo), **annata** da… a…, ordinamento e "Nascondi distillati".
- **🔥 Occasioni**: le aste che rispettano il tuo obiettivo.
- **📊 Riepilogo**: totali delle aste aperte (lotti, bottiglie, valore delle offerte attuali, valore di mercato stimato, occasioni) e un istogramma orizzontale delle tipologie di vino, per numero di lotti, valore delle offerte o valore di mercato. Clicca una barra per vedere i lotti di quella tipologia.
- **Tutti i lotti**: ogni lotto letto, con il giudizio (*Affare*, *Interessante*, *Prezzo di mercato*, *Sopra il mercato*).
- **Da valutare**: i vini di cui l'app non conosce ancora il valore. Scrivi il prezzo a bottiglia direttamente lì: ci sono i link per cercarlo su Wine-Searcher, Vivino e Google. Il valore che inserisci (anche con **Correggi il valore**) ha sempre la precedenza sulle altre fonti, vale per quel vino e quell'annata anche nelle aste future e viene salvato nel database dell'app. Una copia leggibile finisce in `data/valori_inseriti.csv`.
- **Storico vendite**: le aste chiuse registrate, con filtri per testo, produttore, tipologia, annata, data di chiusura e prezzo di chiusura (del lotto o a bottiglia), ordinamento e riepilogo (numero di vendite e prezzo mediano a bottiglia). C'è anche un riquadro per importare un tuo CSV di vendite passate.
- **Come funziona**: la spiegazione di ogni voce.

Per ogni lotto la colonna di destra mostra il conto completo: offerta + commissione Catawiki + spedizione = totale, diviso per le bottiglie, contro il valore di mercato. La commissione è la tariffa pubblicata da Catawiki (9% + 3 €). **La spedizione viene letta da Catawiki** (segno ✓). Catawiki la carica con una richiesta separata, quindi il pulsante va istruito una volta sola: apri la pagina di un lotto di vino, scorri finché vedi il costo di spedizione e premi il pulsante lì. Da quel momento, a ogni pressione, legge la spedizione verso Italia e Spagna per un massimo di 20 lotti (`browser.dettagli`), cominciando da quelli che chiudono prima e ognuno una sola volta. Finché la spedizione di un lotto non è letta, si usa la stima, segnata con ⚠.

Nella scheda **Occasioni**, sotto le occasioni sicure, la sezione **Da verificare** mostra i lotti che superano il tuo sconto ma hanno un valore di mercato solo indicativo. Sotto c'è **fino a che offerta conviene salire** per restare nel tuo sconto.

## Punteggi dei vini

- **★ Vivino** (automatico): valutazione media degli utenti Vivino, su scala 1–5, con il numero di voti. Dopo ogni pressione del pulsante l'app cerca in background i vini nuovi, al massimo una volta ogni 30 giorni per vino. Se Vivino mostra anche un prezzo in euro per quell'annata, lo usa come fonte di valore secondaria. Vivino non ha un'API ufficiale: l'app usa la sua ricerca pubblica, con poche richieste distanziate, e se Vivino la blocca smette di cercare. Per una prova: `python -m cwmon vivino "Sassicaia 2015"`.
- **✎ Critica** (manuale): James Suckling, Parker e simili sono a pagamento e non si possono leggere in automatico. Puoi scriverli tu quando inserisci il valore di un vino (campo "es. JS 95") o nella colonna `punteggio` di `riferimenti.csv`.

## Come stima il valore di mercato

| Fonte | Affidabilità | Come funziona |
|---|---|---|
| `riferimenti.csv` | alta (90%) | I prezzi che inserisci tu, per bottiglia (da Wine-Searcher, Vivino, la tua enoteca…) |
| Storico stessa annata | 45–85% | Prezzi finali delle aste Catawiki chiuse, registrati automaticamente dall'app. Più vendite = più affidabile |
| Prezzo Vivino | 45% | Prezzo da negozio mostrato da Vivino per quell'annata. Di solito è più alto del prezzo in asta, quindi da solo non basta per segnalare un'occasione |
| Storico altre annate | 35% | Stesso vino, annate diverse: mostrato in dashboard ma sotto la soglia degli avvisi |

Se ci sono più fonti, il valore è una media pesata sull'affidabilità. Quando le fonti concordano l'affidabilità sale, quando divergono scende.

> **All'inizio lo storico è vuoto.** Nelle prime settimane le valutazioni vengono soprattutto dai vini che hai messo in `riferimenti.csv`. Lo storico cresce a ogni pressione del pulsante, con i prezzi finali delle aste chiuse che avevi visto.

### Il file `riferimenti.csv`

```csv
vino,annata,prezzo_bottiglia,fonte,punteggio,note
Tenuta San Guido Sassicaia Bolgheri,2015,330,wine-searcher,JS 97,
Bollinger Special Cuvée Champagne,,55,vivino,,annata vuota = qualunque annata/NV
```

- **I prezzi già presenti sono solo esempi**: sostituiscili con i tuoi.
- Il nome viene confrontato in modo "elastico" (accenti, maiuscole, "Château", "Domaine"… non contano). Scrivi produttore + vino + denominazione. Un nome troppo generico come "Barolo" verrebbe abbinato a tutti i Barolo.
- Il prezzo è **per bottiglia da 0,75 L**, IVA inclusa, spedizione esclusa.
- Il modo più comodo per aggiungere righe è la scheda **Da valutare** della dashboard.

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
**Lascia aperta la finestra nera**: finché è aperta funzionano la dashboard, il pulsante e il bot.

### 5. Installa il pulsante (una volta sola, e dopo ogni aggiornamento)
Al primo avvio si apre la pagina `http://localhost:8000/installa.html`. Trascina il pulsante rosso **🍷 Cantina Radar** nella barra dei preferiti del browser. La pagina spiega anche come mostrare la barra se non la vedi.

### 6. Usalo
1. Su catawiki.com apri le aste di vino. Il modo migliore è la categoria **Vino** con il filtro *"Chiude oggi"*.
2. Premi **🍷 Cantina Radar** nei preferiti.
3. In basso a destra compare un pannello che legge la pagina corrente e **tutte le successive dell'elenco** (fino a 30 pagine, `browser.pagine` in `config.yaml`): una pressione nel tardo pomeriggio copre tutte le chiusure della giornata. Poi si apre Cantina Radar con i risultati. Se il browser blocca la finestra, premi **Apri i risultati →** nel pannello. Le occasioni sopra soglia ti arrivano anche su Telegram.
4. Ripeti quando vuoi aggiornare le offerte, per esempio nell'ultima ora prima della chiusura. Ogni pressione registra anche i **prezzi finali** delle aste già chiuse che avevi visto: così lo storico si arricchisce da solo.

Puoi premere il pulsante **tutte le volte che vuoi**: ogni pressione aggiorna le offerte (utile nell'ultima ora prima delle chiusure), mentre gli avvisi Telegram non si ripetono per lo stesso lotto e la spedizione di un lotto si legge una sola volta.


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

Gli avvisi partono quando premi il pulsante e trovi lotti sopra soglia che chiudono entro la finestra impostata. Ogni lotto genera al massimo due avvisi: il primo, e un'**ultima chiamata** se lo riaggiorni negli ultimi 45 minuti ed è ancora conveniente.

---

## Configurazione (`config.yaml`)

I parametri principali (sono tutti commentati nel file):
- `categories`: 443 Vino, 961 Champagne, 971 Porto e vini dolci (437 Whisky disponibile ma il parser è pensato per il vino)
- `paese` e `spedizione`: paese di consegna e costo stimato per lotto e per bottiglia in più, per Italia e Spagna (default 25 € + 2 €). Si cambiano anche dalla dashboard. Controlla sempre la cifra reale sulla pagina del lotto
- `sconto_minimo`, `ore_alla_chiusura`, `affidabilita_minima`, `budget_massimo`
- `includi` / `escludi`: parole chiave (es. `includi: ["barolo", "brunello", "bordeaux"]`)

---

## Comandi da terminale (facoltativo)

Serve Python 3.10 o superiore.

```bash
pip install -r requirements.txt
cp .env.example .env          # inserisci token e chat id
python -m cwmon doctor        # prova la lettura automatica (oggi bloccata da Catawiki)
python -m cwmon demo          # dashboard con dati di esempio in site-demo/index.html
python -m cwmon start --lan   # quello che usano gli script: dashboard + pulsante + bot
python -m cwmon serve         # apre la dashboard su http://localhost:8000
python -m cwmon bot           # bot con risposte immediate
python -m cwmon vivino "Sassicaia 2015"   # prova la ricerca del punteggio Vivino
python -m pytest              # test automatici
```

---

## Limiti da conoscere

- **Catawiki non ha un'API pubblica e blocca le richieste automatiche.** Il pulsante legge solo ciò che il tuo browser vede già. Per farlo usa lo stesso endpoint delle offerte live che usa la pagina, e legge al massimo poche pagine per pressione, una ogni 1,5 secondi. Se Catawiki cambia la struttura delle pagine, il pulsante potrebbe trovare meno lotti o titoli incompleti: segnalamelo.
- **Niente avvisi mentre sei lontano dal computer.** Le valutazioni si aggiornano quando premi il pulsante.
- **Gli avvisi sono indicativi.** Verifica sempre livello del vino, condizioni di conservazione, spedizione reale e dazi (i venditori extra-UE possono comportare IVA all'importazione).
- **L'ultimo minuto conta.** Molte offerte arrivano negli ultimi minuti: lo sconto a 3 ore dalla chiusura tende a ridursi. Per questo l'app ti dà l'**offerta massima**, non solo lo sconto attuale.

---

## Struttura del progetto

```
cwmon/
  web/             pulsante per il browser (bookmarklet), pagina di installazione e di importazione
  server.py        server locale: dashboard, importazione, impostazioni, prezzi e storico
  vivino.py        punteggio Vivino (ricerca pubblica, con archivio locale)
  lotdetails.py    spedizione e commissione lette dalla pagina del lotto
  catawiki.py      interpretazione dei dati Catawiki (offerte live, elenchi)
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
