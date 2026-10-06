# CarWatch 🚗

Rastreador de inventario de autos usados en concesionarias de Montreal. Revisa
cada dealer a su ritmo (respetando `robots.txt`), guarda el historial de precios
en SQLite, puntua cada auto 🟢 / 🟡 / 🔴 y genera un informe diario y una web.

## Instalacion

```bash
git clone https://github.com/katherinemli/carwatch.git
cd carwatch
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m carwatch run               # primera corrida
cat reports/latest.md                 # el informe
python3 ui/app.py                     # la web en http://localhost:8080 (PORT para cambiarlo)
```

Para que corra solo cada noche (03:15), en `crontab -e`:

```
15 3 * * * cd ~/carwatch && .venv/bin/python -m carwatch run
```

La web ya viene compilada en `ui/dist/`. Si cambias el codigo de `ui-src/`:
`cd ui-src && npm install && npm run build` y copia `ui-src/dist/` a `ui/dist/`.

## Comandos

```bash
python3 -m carwatch status            # que dealer toca y cuando
python3 -m carwatch run               # corrida manual (respeta las cadencias)
python3 -m carwatch run --force       # ignora las cadencias
python3 -m carwatch run --only mazda_gabriel
python3 -m carwatch report            # regenera el informe sin scrapear
python3 -m carwatch probe             # revisa robots.txt sin tocar inventario
python3 -m carwatch history --key VIN_O_STOCK
```

## Como decide 🟢 / 🟡 / 🔴

**Filtros duros** — lo unico que descarta de verdad. Si falla uno, el coche va a
la caja ⬛ *Fuera* (se sigue guardando, solo no se propone):

- usado · automatico · gasolina · con precio publicado
- **marca que no sea cara de reparar**. Es tu primer auto y va sin garantia: en
  una marca de piezas caras y taller especializado, una averia corriente es una
  factura de miles. La lista esta en `risk_rules.json` → `brand_repair.caro`, y
  el filtro se apaga con `filters.exclude_high_repair_brands` en `config.json`.

**Precio y trayecto ya NO descartan.** Bajan la nota y nunca dejan un auto en
verde, pero el coche se guarda entero, con su historial de precios. Lo que
decide **que ves** son los sliders de la web: mueve *Precio max* o *Trayecto max*
y pulsa **Aplicar**. Eso es todo lo que hacen — ni cambian lo que se rastrea, ni
lo que se guarda, ni la nota de ningun auto.

**Puntuacion:** km relativos a la edad (no km absolutos) · edad · facilidad de
reparar la marca · puntos debiles conocidos del modelo · gasolina · cercania ·
precio contra la mediana de coches parecidos que el propio historial acumula.

- **🟢** = destaca de verdad: en tu objetivo, cerca, km sensatos, marca barata de
  mantener y sin ningun punto debil caro conocido.
- **🟡** = candidato razonable, la inspeccion de ~$100 es el paso siguiente.
- **🔴** = no gastes ni tiempo ni dinero en inspeccionarlo.

Un precio ridiculamente bajo **baja** la nota, no la sube.

## Las notas por modelo no son etiquetas de fiabilidad

Son **la lista de la compra para el mecanico**: que mirar en ese modelo
concreto. Cada coche tiene sus manias y saberlas es lo util; poner "fiabilidad
por debajo del promedio" no lo es. Viven en `risk_rules.json` → `model_checks`,
y cada una tiene una `severidad`:

- `alta` = el punto debil conocido es una **reparacion cara**. No descalifica,
  pero ese modelo nunca sale en verde sin pasar por el elevador.
- `media` / `baja` = miralo, pero pesa poco.

Anadir un modelo es una linea mas en ese fichero.

## Comparar concesionarias sin que las matematicas te enganen

«Uno tiene 111 autos y 6 me sirven; otro tiene 59 y 3. ¿El segundo es mejor?»
No: 5,4 % contra 5,1 % es la misma cosa. Con 6 y 3 aciertos, que se venda un
coche manana le da la vuelta al orden.

La web lo dibuja honestamente (`carwatch/stats.py`):

- **El punto** = la tasa **ajustada**. A quien tiene pocos autos observados se le
  hace menos caso y se le acerca a la media de todos los lotes. Con 20 autos casi
  no cuenta lo suyo; con 500, manda del todo. (Beta-binomial; el peso del
  "empujon" es `stats.prior_strength` en `config.json`.)
- **La barra** = el margen de error real (intervalo de Wilson). Cuantos menos
  autos, mas larga.
- **Si dos barras se solapan, la respuesta honesta es "todavia no se sabe"**, y
  eso es exactamente lo que dice el texto de debajo del grafico.

La **distancia no entra** en esa tasa a proposito: es la misma para todos los
autos de un lote, asi que dejaria a los de Longueuil en cero sin decir nada de su
inventario. La distancia se mira aparte, en la columna Zona.

## La seccion 📈 Movimientos

No es una lista de bajas. Que un coche salga del inventario no dice si se
vendio, si lo retiraron o si le cambiaron la referencia — no es accionable. Lo
que si dice algo es **como se comporta el lote**:

- **⏱️ ¿Cuanto aguantan?** — mediana de dias que dura un coche *de tu rango*
  frente al resto del lote. Si los tuyos vuelan, hay que llamar el mismo dia; si
  se quedan parados, hay margen para esperar una bajada. Solo cuentan los que
  **vimos llegar**: de los que ya estaban ahi no sabemos cuando se publicaron.
- **🔁 El mismo auto, subido otra vez** — detectado por **VIN**, asi que es el
  mismo coche de verdad. Un lote que quita y vuelve a poner el mismo auto esta
  tanteando: ese precio no es firme.
- **🎢 Precios que suben y bajan** — no una rebaja, sino un precio que se ha
  movido en las **dos** direcciones.

Estas tres necesitan historial. Con dos dias de datos salen vacias y lo dicen;
se llenan solas en dos o tres semanas.

## Ficheros que puedes editar

| Fichero | Para que |
|---|---|
| `config.json` | presupuesto, tope de trayecto, impuestos, cadencias adaptativas, donde arrancan los sliders (`ui`) y la estadistica de dealers (`stats`) |
| `dealers.json` | dealers, cada cuantos dias, y **los minutos de trayecto** |
| `risk_rules.json` | que marcas son caras de reparar (`brand_repair`) y que revisar en cada modelo (`model_checks`) |

Los minutos de trayecto son **estimaciones mias**, no tiempos calculados.
Ajustalos cuando conozcas los trayectos de verdad: mandan sobre la nota de cada
auto y sobre el slider de trayecto de la web.

## Que hace para ser respetuoso

- Lee y **obedece** `robots.txt`, incluidos comodines (`Disallow: /*?*`), que el
  parser estandar de Python ignora en silencio.
- Respeta `Crawl-delay` (5-10s segun el sitio) y nunca va mas rapido.
- No toca rutas prohibidas (por ejemplo `/used/detail.html` en D2C).
- No usa URLs con parametros donde el sitio los prohibe.
- Peticiones condicionales (`ETag`/`If-Modified-Since`): si nada cambio, el
  servidor responde 304 y no se descarga nada.
- Tope de peticiones por dealer y corrida.
- **Si encuentra un muro anti-bot, se retira y marca el dealer para revision
  manual.** Nunca intenta esquivarlo.

## Dealers

Los dos que si dan coches en tu rango van a diario; el resto cada 3-4 dias.
La frecuencia se ajusta sola: si un dealer empieza a dar candidatos sube a
diario, y si pasa 60 dias sin un solo coche en tu rango baja a semanal.

**Volkswagen Gabriel St-Laurent** esta desactivado: su sitio tiene un muro
anti-bot. Te queda cerca, asi que vale la pena que le eches un ojo tu misma
de vez en cuando.

## Ampliar el radio mas adelante

Si en un par de meses los cercanos no dan nada, el historial te lo dira. Para
ampliar a Anjou / Longueuil / Verdun: anade el dealer a `dealers.json` y sube
`max_transit_min` en `config.json`. Chomedey/Laval queda fuera del tope actual
a proposito (~2h).
