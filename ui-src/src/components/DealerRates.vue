<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ dealers: Array, meta: Object })

const pc = n => (n * 100)
const fmt = n => pc(n).toFixed(1).replace('.', ',') + ' %'

// Solo entran los que han sido observados de verdad. Un dealer sin una sola
// corrida no tiene una tasa "baja": no tiene tasa.
const rows = computed(() =>
  (props.dealers || []).filter(d => d.enabled && d.observed > 0))
const pending = computed(() =>
  (props.dealers || []).filter(d => d.enabled && d.observed === 0))

// Escala compartida por todas las filas. Una sola escala, siempre desde 0:
// empezar un eje en otro sitio hace que diferencias minusculas parezcan abismos.
const scaleMax = computed(() => {
  const hi = Math.max(0.06, ...rows.value.map(d => d.rate_hi))
  return Math.ceil(hi * 100 / 5) * 5 / 100
})
const x = v => (v / scaleMax.value) * 100 + '%'
const ticks = computed(() => {
  const step = scaleMax.value > 0.3 ? 0.1 : 0.05
  const out = []
  for (let v = 0; v <= scaleMax.value + 1e-9; v += step) out.push(v)
  return out
})

const hover = ref(null)
const zoneLabel = t => ({ 1: 'cerca', 2: 'media', 3: 'lejos' }[t] || '—')
</script>

<template>
  <div class="rates">
    <div class="rates-head">
      <span class="rates-title">De cada 100 autos que pasan por el lote, cuántos te sirven</span>
      <span class="rates-sub">punto = estimación · barra = margen de error · línea a trazos = media de todos</span>
    </div>

    <div class="rates-plot">
      <div class="gridlayer">
        <div class="tickline" v-for="t in ticks" :key="'t' + t" :style="{ left: x(t) }"></div>
        <div class="meanline" :style="{ left: x(meta.prior_mean) }"></div>
      </div>

      <div class="rrow" v-for="d in rows" :key="d.id"
           :class="{ thin: !d.enough_data, hot: hover === d.id }"
           @mouseenter="hover = d.id" @mouseleave="hover = null">
        <div class="rname">{{ d.name }}</div>
        <div class="rtrack">
          <div class="rci" :style="{ left: x(d.rate_lo), width: x(d.rate_hi - d.rate_lo) }"></div>
          <div class="rdot" :style="{ left: x(d.rate_adj) }"></div>
        </div>
        <div class="rval">
          <b>{{ fmt(d.rate_adj) }}</b>
          <span class="off">{{ d.hits_ever }} de {{ d.observed }}</span>
        </div>

        <div v-if="hover === d.id" class="rtip">
          <b>{{ d.name }}</b><br>
          Vistos {{ d.observed }} autos · {{ d.hits_ever }} te servían.<br>
          Tasa cruda {{ fmt(d.rate || 0) }} · ajustada <b>{{ fmt(d.rate_adj) }}</b><br>
          Margen real: entre {{ fmt(d.rate_lo) }} y {{ fmt(d.rate_hi) }}<br>
          <span v-if="!d.enough_data" class="warn">Menos de {{ meta.min_sample }} autos vistos: el número aún baila mucho.</span>
        </div>
      </div>
    </div>

    <div class="axis">
      <span v-for="(t, i) in ticks" :key="'a' + t"
            :style="{ left: x(t), transform: i === 0 ? 'none' : i === ticks.length - 1 ? 'translateX(-100%)' : 'translateX(-50%)' }">
        {{ Math.round(t * 100) }} %
      </span>
      <span class="meanlabel" :style="{ left: x(meta.prior_mean) }">media {{ fmt(meta.prior_mean) }}</span>
    </div>

    <p v-if="meta.verdict" class="rverdict" :class="{ solid: meta.verdict.separated }">
      {{ meta.verdict.separated ? '✔' : '≈' }} {{ meta.verdict.text }}
    </p>

    <p v-if="pending.length" class="rpending">
      Sin datos todavía (aún no se han rastreado): {{ pending.map(d => d.name).join(' · ') }}.
    </p>
  </div>
</template>

<style scoped>
.rates{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px 12px}
.rates-head{display:flex;flex-direction:column;gap:2px;margin-bottom:16px}
.rates-title{font-size:13.5px;font-weight:650;color:var(--ink)}
.rates-sub{font-size:12px;color:var(--muted)}

/* Un solo juego de medidas para la fila Y para la rejilla: asi el eje cae
   siempre justo debajo de los puntos, no debajo de los nombres. */
.rates{--namew:190px;--valw:104px;--gap:12px}
.rates-plot{position:relative}
.rrow{display:grid;grid-template-columns:var(--namew) 1fr var(--valw);
  align-items:center;gap:var(--gap);padding:5px 0;position:relative;border-radius:6px}
.gridlayer{position:absolute;top:0;bottom:0;
  left:calc(var(--namew) + var(--gap));right:calc(var(--valw) + var(--gap));pointer-events:none}
.rrow.hot{background:color-mix(in srgb,var(--accent) 7%,transparent)}
.rname{font-size:13px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rtrack{position:relative;height:16px}
.rci{position:absolute;top:7px;height:2px;background:var(--accent);opacity:.34;border-radius:2px;min-width:2px}
.rdot{position:absolute;top:3px;width:10px;height:10px;margin-left:-5px;border-radius:50%;
  background:var(--accent);box-shadow:0 0 0 2px var(--card)}
.rrow.thin .rci,.rrow.thin .rdot{background:var(--grey)}
.rval{font-size:12.5px;text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.rval b{color:var(--ink)}
.rval .off{display:block;font-size:11px}

/* rejilla al fondo: presente pero nunca compitiendo con los datos */
.tickline,.meanline{position:absolute;top:0;bottom:0;width:1px;pointer-events:none}
.tickline{background:var(--line)}
.meanline{border-left:1px dashed var(--muted);opacity:.55}

.axis{position:relative;height:30px;margin-top:2px;font-size:11px;color:var(--muted);
  margin-left:calc(var(--namew) + var(--gap));margin-right:calc(var(--valw) + var(--gap))}
.axis span{position:absolute;white-space:nowrap;font-variant-numeric:tabular-nums}
.axis .meanlabel{top:14px;transform:translateX(-50%);font-size:10.5px;opacity:.8}

.rtip{position:absolute;left:var(--namew);top:100%;z-index:5;background:var(--card);color:var(--ink);
  border:1px solid var(--line);border-radius:8px;padding:9px 11px;font-size:12px;line-height:1.55;
  box-shadow:0 8px 24px rgba(0,0,0,.16);white-space:nowrap;pointer-events:none}
.rtip .warn{color:var(--yellow)}
.rverdict{margin:16px 0 0;font-size:12.5px;color:var(--muted);line-height:1.6;
  border-top:1px solid var(--line);padding-top:12px}
.rverdict.solid{color:var(--ink)}
.rpending{margin:8px 0 0;font-size:12px;color:var(--muted)}
@media (max-width:560px){
  .rates{--namew:104px;--valw:78px;--gap:8px}
  .rname{font-size:12px}
  .rtip{left:0;white-space:normal;max-width:min(88vw,340px)}
}
</style>
