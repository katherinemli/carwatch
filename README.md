# CarWatch 🚗

**[Français](#français) · [English](#english)**

---

## Français

Outil de suivi de l'inventaire de véhicules d'occasion chez les concessionnaires
de Montréal. Il visite chaque concessionnaire à son propre rythme (en respectant
`robots.txt`), conserve l'historique des prix dans SQLite, attribue une cote
🟢 / 🟡 / 🔴 à chaque véhicule et produit un rapport quotidien ainsi qu'une
interface web.

### Installation

```bash
git clone https://github.com/katherinemli/carwatch.git
cd carwatch
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m carwatch run               # première exécution
cat reports/latest.md                 # le rapport
python3 ui/app.py                     # l'interface sur http://localhost:8080 (variable PORT pour la changer)
```

Pour une exécution automatique chaque nuit (3 h 15), dans `crontab -e` :

```
15 3 * * * cd ~/carwatch && .venv/bin/python -m carwatch run
```

L'interface est déjà compilée dans `ui/dist/`. Si vous modifiez le code de
`ui-src/` : `cd ui-src && npm install && npm run build`, puis copiez
`ui-src/dist/` vers `ui/dist/`.

### Commandes

```bash
python3 -m carwatch status            # quel concessionnaire est dû, et quand
python3 -m carwatch run               # exécution manuelle (respecte les cadences)
python3 -m carwatch run --force       # ignore les cadences
python3 -m carwatch run --only mazda_gabriel
python3 -m carwatch report            # régénère le rapport sans collecter
python3 -m carwatch probe             # vérifie robots.txt sans toucher à l'inventaire
python3 -m carwatch history --key VIN_OU_STOCK
```

### Comment il décide 🟢 / 🟡 / 🔴

**Filtres stricts** — les seuls qui écartent vraiment un véhicule. S'il en échoue
un, il va dans la boîte ⬛ *Exclus* (il est quand même conservé, seulement pas
proposé) :

- usagé · automatique · essence · prix affiché
- **marque qui n'est pas coûteuse à réparer**. Pour un premier véhicule sans
  garantie, une panne ordinaire sur une marque aux pièces chères et au garage
  spécialisé, c'est une facture de plusieurs milliers de dollars. La liste se
  trouve dans `risk_rules.json` → `brand_repair.caro`, et le filtre se désactive
  avec `filters.exclude_high_repair_brands` dans `config.json`.

**Le prix et le trajet n'écartent PLUS rien.** Ils abaissent la cote et
empêchent un véhicule d'être vert, mais le véhicule est conservé au complet, avec
son historique de prix. Ce qui décide **ce que vous voyez**, ce sont les curseurs
de l'interface : déplacez *Prix max* ou *Trajet max* et cliquez sur
**Appliquer**. C'est tout ce qu'ils font — ils ne changent ni ce qui est suivi,
ni ce qui est conservé, ni la cote d'aucun véhicule.

**Pointage :** kilométrage relatif à l'âge (pas le kilométrage absolu) · âge ·
facilité de réparation de la marque · points faibles connus du modèle · essence
· proximité · prix comparé à la médiane des véhicules semblables accumulés dans
l'historique.

- **🟢** = se démarque vraiment : dans l'objectif, proche, kilométrage
  raisonnable, marque peu coûteuse à entretenir et aucun point faible coûteux
  connu.
- **🟡** = candidat raisonnable; l'inspection d'environ 100 $ est la prochaine
  étape.
- **🔴** = ne perdez ni temps ni argent à le faire inspecter.

Un prix ridiculement bas **abaisse** la cote, il ne l'augmente pas.

### Les notes par modèle ne sont pas des étiquettes de fiabilité

C'est **la liste d'épicerie pour le mécanicien** : quoi vérifier sur ce modèle
précis. Chaque véhicule a ses manies et c'est ça qui est utile; écrire
« fiabilité sous la moyenne » ne l'est pas. Elles se trouvent dans
`risk_rules.json` → `model_checks`, et chacune a une `severidad` :

- `alta` = le point faible connu est une **réparation coûteuse**. Ça ne
  disqualifie pas, mais ce modèle n'est jamais vert sans passer sur le pont
  élévateur.
- `media` / `baja` = à vérifier, mais ça pèse peu.

Ajouter un modèle, c'est une ligne de plus dans ce fichier.

### Comparer les concessionnaires sans se faire avoir par les maths

« L'un a 111 véhicules et 6 me conviennent; l'autre en a 59 et 3. Le deuxième
est-il meilleur? » Non : 5,4 % contre 5,1 %, c'est la même chose. Avec 6 et 3
réussites, il suffit qu'un véhicule se vende demain pour inverser l'ordre.

L'interface le montre honnêtement (`carwatch/stats.py`) :

- **Le point** = le taux **ajusté**. Un concessionnaire avec peu de véhicules
  observés compte moins et est ramené vers la moyenne de tous les lots. Avec 20
  véhicules, ses propres données comptent à peine; avec 500, elles dominent.
  (Bêta-binomiale; la force de cet ajustement est `stats.prior_strength` dans
  `config.json`.)
- **La barre** = la vraie marge d'erreur (intervalle de Wilson). Moins il y a de
  véhicules, plus elle est longue.
- **Si deux barres se chevauchent, la réponse honnête est « on ne le sait pas
  encore »**, et c'est exactement ce que dit le texte sous le graphique.

La **distance n'entre pas** dans ce taux, volontairement : elle est la même pour
tous les véhicules d'un lot, donc elle mettrait ceux de Longueuil à zéro sans
rien dire de leur inventaire. La distance est présentée à part, dans la colonne
Zone.

### La section 📈 Mouvements

Ce n'est pas une liste de retraits. Qu'un véhicule disparaisse de l'inventaire
ne dit pas s'il a été vendu, retiré ou renuméroté — rien d'utile pour agir. Ce
qui en dit long, c'est **le comportement du lot** :

- **⏱️ Combien de temps restent-ils?** — nombre médian de jours qu'un véhicule
  *dans votre fourchette* reste affiché, comparé au reste du lot. S'ils partent
  vite, il faut appeler le jour même; s'ils restent, on peut attendre une baisse
  de prix. Seuls comptent ceux qu'on **a vus arriver** : pour ceux déjà présents,
  on ne sait pas quand ils ont été publiés.
- **🔁 Le même véhicule, republié** — détecté par **NIV**, donc c'est vraiment
  le même véhicule. Un lot qui retire et republie le même véhicule teste le
  marché : ce prix n'est pas ferme.
- **🎢 Des prix qui montent et descendent** — pas une baisse, mais un prix qui a
  bougé dans les **deux** sens.

Ces trois indicateurs ont besoin d'historique. Avec deux jours de données, ils
sont vides et le disent; ils se remplissent d'eux-mêmes en deux ou trois
semaines.

### Fichiers modifiables

| Fichier | À quoi il sert |
|---|---|
| `config.json` | budget, trajet maximal, taxes, cadences adaptatives, position de départ des curseurs (`ui`) et statistiques des concessionnaires (`stats`) |
| `dealers.json` | concessionnaires, fréquence de visite et **minutes de trajet** |
| `risk_rules.json` | marques coûteuses à réparer (`brand_repair`) et points à vérifier par modèle (`model_checks`) |

Les minutes de trajet sont des **estimations**, pas des temps calculés.
Ajustez-les quand vous connaîtrez les vrais trajets : elles influencent la cote
de chaque véhicule et le curseur de trajet de l'interface.

### Ce qu'il fait pour rester respectueux

- Il lit et **respecte** `robots.txt`, y compris les jokers (`Disallow: /*?*`),
  que l'analyseur standard de Python ignore silencieusement.
- Il respecte `Crawl-delay` (5 à 10 s selon le site) et ne va jamais plus vite.
- Il ne touche jamais aux chemins interdits (par exemple `/used/detail.html`
  chez D2C).
- Il n'utilise pas d'URL avec paramètres là où le site les interdit.
- Requêtes conditionnelles (`ETag` / `If-Modified-Since`) : si rien n'a changé,
  le serveur répond 304 et rien n'est téléchargé.
- Plafond de requêtes par concessionnaire et par exécution.
- **S'il rencontre un mur anti-robot, il se retire et signale le
  concessionnaire pour une vérification manuelle.** Il n'essaie jamais de le
  contourner.

### Concessionnaires

Les deux qui offrent des véhicules dans la fourchette sont visités chaque jour;
les autres, aux 3 ou 4 jours. La fréquence s'ajuste d'elle-même : si un
concessionnaire commence à produire des candidats, il passe en quotidien, et
s'il passe 60 jours sans un seul véhicule dans la fourchette, il passe en
hebdomadaire.

**Volkswagen Gabriel St-Laurent** est désactivé : son site a un mur anti-robot.
Il vaut la peine d'y jeter un coup d'œil manuellement de temps en temps.

### Élargir le rayon plus tard

Si les concessionnaires proches ne donnent rien d'ici quelques mois,
l'historique le dira. Pour élargir à Anjou / Longueuil / Verdun : ajoutez le
concessionnaire à `dealers.json` et augmentez `max_transit_min` dans
`config.json`. Chomedey/Laval est volontairement hors de la limite actuelle
(~2 h).

---

## English

Used-car inventory tracker for Montreal dealerships. It visits each dealer at
its own pace (respecting `robots.txt`), keeps price history in SQLite, rates
every car 🟢 / 🟡 / 🔴, and produces a daily report and a web UI.

### Installation

```bash
git clone https://github.com/katherinemli/carwatch.git
cd carwatch
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m carwatch run               # first run
cat reports/latest.md                 # the report
python3 ui/app.py                     # web UI at http://localhost:8080 (set PORT to change it)
```

To run it automatically every night (3:15 a.m.), add to `crontab -e`:

```
15 3 * * * cd ~/carwatch && .venv/bin/python -m carwatch run
```

The web UI ships prebuilt in `ui/dist/`. If you change the code in `ui-src/`:
`cd ui-src && npm install && npm run build`, then copy `ui-src/dist/` to
`ui/dist/`.

### Commands

```bash
python3 -m carwatch status            # which dealer is due, and when
python3 -m carwatch run               # manual run (respects cadences)
python3 -m carwatch run --force       # ignores cadences
python3 -m carwatch run --only mazda_gabriel
python3 -m carwatch report            # regenerate the report without scraping
python3 -m carwatch probe             # check robots.txt without touching inventory
python3 -m carwatch history --key VIN_OR_STOCK
```

### How it decides 🟢 / 🟡 / 🔴

**Hard filters** — the only things that truly rule a car out. If it fails one,
it goes into the ⬛ *Out* box (still stored, just not suggested):

- used · automatic · gasoline · listed price
- **a brand that isn't expensive to repair**. For a first car with no warranty,
  an ordinary breakdown on a brand with pricey parts and specialist shops is a
  bill in the thousands. The list lives in `risk_rules.json` →
  `brand_repair.caro`, and the filter is turned off with
  `filters.exclude_high_repair_brands` in `config.json`.

**Price and commute NO LONGER rule anything out.** They lower the score and keep
a car from ever being green, but the car is stored in full, with its price
history. What decides **what you see** are the sliders in the web UI: move
*Max price* or *Max commute* and click **Apply**. That's all they do — they don't
change what's tracked, what's stored, or any car's score.

**Scoring:** mileage relative to age (not absolute mileage) · age · how easy the
brand is to repair · known weak points of the model · gasoline · proximity ·
price against the median of similar cars accumulated in the history.

- **🟢** = genuinely stands out: within target, close by, sensible mileage, a
  brand that's cheap to maintain and no known expensive weak point.
- **🟡** = reasonable candidate; the ~$100 inspection is the next step.
- **🔴** = don't spend time or money having it inspected.

A ridiculously low price **lowers** the score, it doesn't raise it.

### Model notes are not reliability labels

They are **the shopping list for the mechanic**: what to check on that specific
model. Every car has its quirks and knowing them is what's useful; saying
"below-average reliability" isn't. They live in `risk_rules.json` →
`model_checks`, and each one has a `severidad` (severity):

- `alta` (high) = the known weak point is an **expensive repair**. It doesn't
  disqualify the car, but that model is never green without going up on the
  lift.
- `media` / `baja` (medium / low) = worth checking, but it carries little
  weight.

Adding a model is one more line in that file.

### Comparing dealers without being fooled by the math

"One has 111 cars and 6 fit; the other has 59 and 3. Is the second one better?"
No: 5.4% versus 5.1% is the same thing. With 6 and 3 hits, one car selling
tomorrow flips the order.

The web UI draws it honestly (`carwatch/stats.py`):

- **The dot** = the **adjusted** rate. A dealer with few observed cars is
  trusted less and pulled toward the average of all lots. With 20 cars its own
  data barely counts; with 500, it dominates. (Beta-binomial; the strength of
  that pull is `stats.prior_strength` in `config.json`.)
- **The bar** = the real margin of error (Wilson interval). The fewer cars, the
  longer it is.
- **If two bars overlap, the honest answer is "we don't know yet"**, and that's
  exactly what the text under the chart says.

**Distance is deliberately left out** of that rate: it's the same for every car
on a lot, so it would put the Longueuil dealers at zero without saying anything
about their inventory. Distance is shown separately, in the Zone column.

### The 📈 Movements section

It isn't a list of removals. A car leaving the inventory doesn't tell you
whether it sold, was pulled, or had its stock number changed — nothing
actionable. What does say something is **how the lot behaves**:

- **⏱️ How long do they last?** — median days a car *in your range* stays
  listed, compared with the rest of the lot. If yours go fast, call the same
  day; if they sit, there's room to wait for a price drop. Only cars **we saw
  arrive** count: for the ones already there, we don't know when they were
  listed.
- **🔁 The same car, relisted** — detected by **VIN**, so it's truly the same
  car. A lot that pulls and relists the same car is testing the market: that
  price isn't firm.
- **🎢 Prices that go up and down** — not a markdown, but a price that has moved
  in **both** directions.

These three need history. With two days of data they're empty and say so; they
fill in on their own within two or three weeks.

### Files you can edit

| File | What it's for |
|---|---|
| `config.json` | budget, commute cap, taxes, adaptive cadences, where the sliders start (`ui`) and dealer statistics (`stats`) |
| `dealers.json` | dealers, how often to visit, and **commute minutes** |
| `risk_rules.json` | which brands are expensive to repair (`brand_repair`) and what to check on each model (`model_checks`) |

Commute minutes are **estimates**, not computed times. Adjust them once you know
the real commutes: they drive each car's score and the commute slider in the web
UI.

### What it does to stay polite

- Reads and **obeys** `robots.txt`, including wildcards (`Disallow: /*?*`),
  which Python's standard parser silently ignores.
- Respects `Crawl-delay` (5–10 s depending on the site) and never goes faster.
- Never touches disallowed paths (for example `/used/detail.html` on D2C).
- Doesn't use URLs with parameters where the site forbids them.
- Conditional requests (`ETag` / `If-Modified-Since`): if nothing changed, the
  server answers 304 and nothing is downloaded.
- A cap on requests per dealer per run.
- **If it hits an anti-bot wall, it backs off and flags the dealer for manual
  review.** It never tries to get around it.

### Dealers

The two that actually have cars in range are visited daily; the rest every 3–4
days. The frequency adjusts itself: if a dealer starts producing candidates it
moves up to daily, and if it goes 60 days without a single car in range it drops
to weekly.

**Volkswagen Gabriel St-Laurent** is disabled: its site has an anti-bot wall.
It's worth checking manually now and then.

### Widening the radius later

If the nearby dealers turn up nothing in a couple of months, the history will
show it. To widen to Anjou / Longueuil / Verdun: add the dealer to
`dealers.json` and raise `max_transit_min` in `config.json`. Chomedey/Laval is
deliberately outside the current cap (~2 h).
