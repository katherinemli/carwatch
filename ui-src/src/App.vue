<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import VehicleCard from './components/VehicleCard.vue'
import DealerRates from './components/DealerRates.vue'
import Movements from './components/Movements.vue'

const data = ref(null)
const err = ref(null)

// Topes de los sliders. Al llegar al final significan "sin tope": nada se
// esconde. Todo lo que se ve aqui es SOLO filtro de pantalla — no cambia ni lo
// que se guarda, ni la nota de ningun auto, ni lo que se rastrea.
const PRICE_TOP = 25000
const TRANSIT_TOP = 120

const draft = reactive({ maxPrice: 12000, maxTransit: 60 })
const applied = reactive({ maxPrice: 12000, maxTransit: 60 })
const defaults = reactive({ maxPrice: 12000, maxTransit: 60 })
const onlyDrops = ref(false)

const dirty = computed(() =>
  draft.maxPrice !== applied.maxPrice || draft.maxTransit !== applied.maxTransit)
function applyFilters () {
  applied.maxPrice = draft.maxPrice
  applied.maxTransit = draft.maxTransit
}
function resetFilters () {
  draft.maxPrice = applied.maxPrice = defaults.maxPrice
  draft.maxTransit = applied.maxTransit = defaults.maxTransit
  onlyDrops.value = false
}
const show = reactive({ GREEN: true, YELLOW: true, RED: false, EXCLUDED: false })

const VERDICTS = [
  { k: 'GREEN', icon: '🟢', label: 'Verde', title: 'Destacan',
    empty: 'Nada en verde con este filtro. Es normal — el historial sigue acumulando.' },
  { k: 'YELLOW', icon: '🟡', label: 'Amarillo', title: 'Razonables — merecen la inspección',
    empty: 'Sin candidatos amarillos con este filtro.' },
  { k: 'RED', icon: '🔴', label: 'Rojo', title: 'No vale la pena inspeccionar',
    empty: 'Nada en rojo con este filtro.' },
  { k: 'EXCLUDED', icon: '⬛', label: 'Fuera', title: 'Descartados por los filtros duros',
    empty: 'Nada descartado con este filtro.' }
]

const money = n => n == null ? '—' : '$' + Number(n).toLocaleString('en-CA')
const priceLabel = n => n >= PRICE_TOP ? 'sin tope' : money(n)
const transitLabel = n => n >= TRANSIT_TOP ? 'sin tope' : n + ' min'
const fmtDate = s => new Date(s).toLocaleString('es-CA', { dateStyle: 'medium', timeStyle: 'short' })
const zoneLabel = t => ({ 1: 'cerca', 2: 'media', 3: 'lejos' }[t] || '—')
const offReason = d => ({ blocked: 'anti-bot, no se toca',
  forbidden: 'su robots.txt lo prohíbe', manual: 'demasiado grande, búsqueda manual'
}[d.platform] || 'desactivado')

const vehicles = computed(() => data.value?.vehicles ?? [])

// El filtro se aplica IGUAL a las cuatro cajas, incluida ⬛ Fuera. Antes los
// descartados se colaban enteros aunque el slider dijera otra cosa.
function visible (v) {
  if (applied.maxPrice < PRICE_TOP && v.price != null && v.price > applied.maxPrice) return false
  if (applied.maxTransit < TRANSIT_TOP && v.transit_min > applied.maxTransit) return false
  if (onlyDrops.value && !(v.price_drop < 0)) return false
  return true
}
const shown = computed(() => vehicles.value.filter(visible))
const hidden = computed(() => vehicles.value.length - shown.value.length)
function filtered (k) {
  return shown.value.filter(v => v.verdict === k)
    .sort((a, b) => (b.score - a.score) || ((a.price || 0) - (b.price || 0)))
}
const count = k => filtered(k).length

onMounted(async () => {
  try {
    const r = await fetch('/api/data')
    if (!r.ok) throw new Error('HTTP ' + r.status)
    data.value = await r.json()
    const u = data.value.ui || {}
    defaults.maxPrice = u.default_max_price ?? 12000
    defaults.maxTransit = u.default_max_transit_min ?? 60
    draft.maxPrice = applied.maxPrice = defaults.maxPrice
    draft.maxTransit = applied.maxTransit = defaults.maxTransit
  } catch (e) {
    err.value = e.message
  }
})
</script>

<template>
  <div class="wrap">
    <h1>🚗 CarWatch</h1>
    <div class="sub" v-if="data">
      {{ vehicles.length }} autos en seguimiento · actualizado {{ fmtDate(data.generated_at) }} · compra prevista en enero
    </div>

    <div v-if="err" class="empty">No pude cargar los datos: {{ err }}</div>
    <div v-else-if="!data" class="empty">Cargando…</div>

    <template v-if="data">
      <div class="counts">
        <div v-for="v in VERDICTS" :key="v.k" class="pill" :class="{ on: show[v.k] }"
             @click="show[v.k] = !show[v.k]">
          <span>{{ v.icon }}</span><span>{{ v.label }}</span><b>{{ count(v.k) }}</b>
        </div>
      </div>

      <div class="controls" :class="{ dirty }">
        <label>Precio máx
          <input type="range" min="2000" :max="PRICE_TOP" step="250" v-model.number="draft.maxPrice">
          <b>{{ priceLabel(draft.maxPrice) }}</b>
        </label>
        <label>Trayecto máx
          <input type="range" min="10" :max="TRANSIT_TOP" step="5" v-model.number="draft.maxTransit">
          <b>{{ transitLabel(draft.maxTransit) }}</b>
        </label>
        <label><input type="checkbox" v-model="onlyDrops"> solo con bajada de precio</label>
        <div class="apply">
          <button class="btn" :disabled="!dirty" @click="applyFilters">Aplicar</button>
          <button class="btn ghost" @click="resetFilters">Restablecer</button>
          <span v-if="dirty" class="hint">sin aplicar</span>
        </div>
        <div class="filternote">
          Esto solo decide <b>qué ves</b>. Todo se sigue guardando y puntuando igual.
          <template v-if="hidden"> Ahora mismo hay <b>{{ hidden }}</b> autos escondidos por el filtro.</template>
        </div>
      </div>

      <template v-for="v in VERDICTS" :key="v.k">
        <template v-if="show[v.k]">
          <h2>{{ v.icon }} {{ v.title }} <span class="off">({{ count(v.k) }})</span></h2>
          <div v-if="!count(v.k)" class="empty">{{ v.empty }}</div>
          <VehicleCard v-for="c in filtered(v.k)" :key="c.id" :v="c" />
        </template>
      </template>

      <h2>🏬 Concesionarias — ¿cuál te va a dar el auto?</h2>

      <div class="explainer">
        <p><b>La pregunta:</b> uno tiene 111 autos y 6 te sirven; otro tiene 59 y 3.
          ¿El segundo es mejor porque «acierta más por auto»?</p>
        <p><b>La respuesta: no, son lo mismo.</b> 6 de 111 es 5,4 % y 3 de 59 es 5,1 %.
          Esa diferencia de 0,3 puntos es mucho más pequeña que el ruido: con 6 y 3 aciertos,
          que se venda un solo coche mañana ya le da la vuelta al orden.
          Y si algo inclina la balanza, es el <b>primero</b>: la misma tasa pero con el doble
          de pruebas detrás, y el doble de candidatos de verdad para ir a ver.</p>
        <p><b>Lo que sí se puede medir</b> es cuánta confianza merece cada número.
          La <b>barra</b> es el rango de tasas que encajan con lo observado — cuantos menos autos,
          más larga. El <b>punto</b> es la estimación después de desconfiar de quien tiene pocos datos:
          con 20 autos vistos, un lote se parece a la media de todos; con 500, sus números mandan.
          Si dos barras se solapan, la respuesta honesta es <b>todavía no se sabe</b>.</p>
      </div>

      <DealerRates :dealers="data.dealers" :meta="data.dealer_meta" />

      <div class="tablewrap dealertable">
        <table>
          <thead>
            <tr><th>Dealer</th><th>Zona</th><th class="num">Cada</th><th>Última</th>
              <th class="num">En el lote</th><th class="num">En tu rango</th><th class="num">Vistos</th></tr>
          </thead>
          <tbody>
            <tr v-for="d in data.dealers" :key="d.id" :class="{ off: !d.enabled }">
              <td>{{ d.name }}<span v-if="!d.enabled" class="off"> — {{ offReason(d) }}</span></td>
              <td><span class="zone" :class="'t' + d.tier">{{ zoneLabel(d.tier) }}</span></td>
              <td class="num">{{ d.cadence_days ? d.cadence_days + 'd' : '—' }}</td>
              <td>
                <span v-if="d.last_run_days === null">nunca</span>
                <span v-else>{{ d.last_run_days === 0 ? 'hoy' : 'hace ' + d.last_run_days + 'd' }}
                  <span v-if="d.last_ok === false">⚠️</span></span>
              </td>
              <td class="num">{{ d.inventory }}</td>
              <td class="num"><b>{{ d.candidates }}</b></td>
              <td class="num off">{{ d.observed }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="tnote">
        <b>En tu rango</b> = de los que están hoy en el lote, cuántos pasan los filtros duros, entran en tu
        presupuesto y puntúan como candidato — la misma cuenta que la tasa de arriba.
        <b>Vistos</b> = todos los que han pasado por ahí desde que miramos; de ahí sale la tasa, por eso crece cada día.
        La <b>distancia no entra</b> en la tasa a propósito: es la misma para todos los autos de un lote
        y dejaría a los de Longueuil en cero sin decir nada de su inventario. Para eso está la columna Zona.
      </p>

      <h2>📈 Movimientos — cómo se comporta cada lote</h2>
      <Movements v-if="data.movements" :m="data.movements" />

      <div class="foot">
        🟢 destaca y merece inspección · 🟡 razonable, la inspección de ~$100 es el paso siguiente ·
        🔴 no gastes en inspeccionarlo · ⬛ fuera por un filtro duro.<br>
        <b>Filtros duros</b> (lo único que descarta de verdad): usado · automático · gasolina ·
        con precio publicado · y <b>marca que no sea cara de reparar</b> — es tu primer auto y va sin
        garantía, así que las marcas de piezas caras y taller especializado quedan fuera.
        Se editan en <code>risk_rules.json</code> y <code>config.json</code>.<br>
        El <b>precio</b> y el <b>trayecto</b> ya no descartan nada: bajan la nota y nunca dejan un auto en verde,
        pero se guarda todo. Sube los sliders para ver lo caro o lo lejano con todo su histórico.<br>
        Las notas por modelo son la <b>lista de la compra para el mecánico</b>, no etiquetas de fiabilidad.
        Cada modelo tiene sus manías; ahí está la de este.<br>
        Los minutos de trayecto son estimaciones guardadas en <code>dealers.json</code>, no tiempos calculados.
        El precio con impuestos no incluye fees del dealer ni SAAQ.
        Esto lista candidatos; no te dice qué comprar.
      </div>
    </template>
  </div>
</template>
