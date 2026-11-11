# Het weer ☀️❄️

Een app voor je telefoon met het weer per uur (48 uur) en per dag (week), en een
pushmelding als het op jouw locatie te koud wordt.

- **De app** (installeerbaar via Chrome) draait op GitHub Pages.
- **De vorstmelding** komt van GitHub Actions, ook als je telefoon of de app uit staat.
- Weerdata: [Open-Meteo](https://open-meteo.com). Pushmeldingen: [ntfy](https://ntfy.sh). Alles gratis.

## Instellen (eenmalig)

1. **Maak een nieuwe, openbare repository** op GitHub, bijvoorbeeld `vorstwacht`.
2. **Upload alle bestanden** (Add file → Upload files).
   Zie je de map `.github` niet? Die is vaak verborgen. Kies dan Add file →
   *Create new file*, typ als naam `.github/workflows/vorstwacht.yml` en plak de inhoud erin.
3. **Zet GitHub Pages aan:** Settings → Pages → Source: *Deploy from a branch* →
   branch `main`, map `/ (root)` → Save. Na een minuut staat de app op
   `https://<jouw-gebruikersnaam>.github.io/vorstwacht/`.
4. **Pushmeldingen:** installeer de app **ntfy** op je telefoon en abonneer je op een
   zelfbedacht, moeilijk te raden woord (bijv. `vorst-mijnnaam-8k3j2`).
   Zet dat woord op GitHub bij Settings → Secrets and variables → Actions →
   *New repository secret*, met de naam `NTFY_TOPIC`.

## App installeren via Chrome (Android)

1. Open het adres van je app in Chrome.
2. Tik op **Installeren** bovenin de app, of via het menu ⋮ → *App installeren*
   (soms *Toevoegen aan startscherm*).
3. Het weer staat nu als app op je startscherm en werkt ook offline met het laatste weerbericht.

## Instellingen aanpassen in de app

Tabblad **Instellingen**:

- **Locatie:** zoek je plaats en tik op het juiste resultaat.
- **Vorstmelding:** tijdstip, temperatuurgrens en hoe ver vooruit gekeken wordt.
- **Koppeling met GitHub** (eenmalig): hiermee stuurt de app je instellingen naar
  `config.json`, zodat de meldingen ook veranderen. Je hebt een toegangssleutel nodig:
  1. GitHub → Settings → Developer settings → Personal access tokens →
     **Fine-grained tokens** → *Generate new token*.
  2. Repository access: *Only select repositories* → je repository (`vorstwacht`).
  3. Permissions: **Contents** en **Actions** op *Read and write*.
  4. Plak de sleutel in de app en tik op *Koppeling opslaan*. Met **Testmelding**
     controleer je meteen of de meldingen werken.

De sleutel blijft alleen op je telefoon. Zonder koppeling kun je `config.json` ook
gewoon op GitHub bewerken met het potloodje.

## Goed om te weten

- GitHub draait de controle elk uur, maar kijkt alleen op jouw uur naar het weer.
  Alleen als de laagste temperatuur op of onder je grens ligt, krijg je een melding.
  GitHub start soms een paar minuten later dan gepland.
- GitHub zet geplande workflows uit na 60 dagen zonder wijzigingen in de repository.
  Instellingen opslaan via de app telt als wijziging. Gaat hij toch uit, dan krijg je
  een e-mail en zet je hem met één klik weer aan.
- De luchttemperatuur is gemeten op 2 meter hoogte. Aan de grond is het vaak een paar
  graden kouder (de app toont beide); kies gerust `2` °C als grens voor nachtvorst aan de grond.
