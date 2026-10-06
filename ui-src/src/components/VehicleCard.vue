<script setup>
const props = defineProps({ v: Object })
const money = n => n == null ? '—' : '$' + Number(n).toLocaleString('en-CA')
const km = n => n == null ? '—' : Number(n).toLocaleString('en-CA')
const LABEL = { GREEN: 'Verde', YELLOW: 'Amarillo', RED: 'Rojo', EXCLUDED: 'Fuera' }

function sparkH (p, hist) {
  const ps = hist.map(h => h.price).filter(x => x != null)
  const lo = Math.min(...ps), hi = Math.max(...ps)
  return hi === lo ? 10 : 4 + 12 * ((p - lo) / (hi - lo))
}
</script>

<template>
  <div class="card" :class="v.verdict">
    <div class="top">
      <div>
        <span class="badge">{{ LABEL[v.verdict] }}</span>
        <span v-if="v.over_budget" class="chip warn">fuera de presupuesto</span>
        <span v-if="v.too_far" class="chip">lejos · {{ v.transit_min }} min</span>
        <span v-if="v.model_severity === 'alta'" class="chip warn">punto débil caro</span>
        <span v-if="v.brand_repair === 'facil'" class="chip ok">barato de reparar</span>
        <div class="name">
          {{ v.year }} {{ v.make }} {{ v.model }}
          <span class="off">{{ v.trim }}</span>
        </div>
      </div>
      <div class="pricebox">
        <div class="price">{{ money(v.price) }}</div>
        <div v-if="v.price_drop < 0" class="drop">↓ {{ money(-v.price_drop) }} desde que apareció</div>
        <div class="off tax">≈ {{ money(v.landed) }} con impuestos</div>
      </div>
    </div>

    <div class="meta">
      <span><b>{{ km(v.mileage) }}</b> km<template v-if="v.km_ratio"> ({{ v.km_ratio.toFixed(2) }}× lo normal)</template></span>
      <span><b>{{ v.transmission_raw || v.transmission }}</b></span>
      <span><b>{{ v.fuel_effective || '—' }}</b></span>
      <span>📍 <b>~{{ v.transit_min }} min</b> <span class="off">(casa {{ v.transit_home }} / trabajo {{ v.transit_work }})</span></span>
      <span>{{ v.vehicle_location || v.dealer_name }}</span>
      <span v-if="v.days_listed !== null">⏳ {{ v.days_listed }} d publicado</span>
      <span v-if="v.price_history && v.price_history.length > 1" class="spark">
        <i v-for="(h, i) in v.price_history" :key="i"
           :style="{ height: sparkH(h.price, v.price_history) + 'px' }"
           :title="money(h.price)"></i>
      </span>
    </div>

    <ul v-if="v.verdict !== 'EXCLUDED' && v.pros.length" class="notes pros">
      <li v-for="(p, i) in v.pros" :key="i">{{ p }}</li>
    </ul>
    <ul v-if="v.notes.length" class="notes">
      <li v-for="(n, i) in v.notes" :key="i">{{ n }}</li>
    </ul>
    <ul v-if="v.verdict === 'EXCLUDED'" class="notes bad">
      <li v-for="(n, i) in v.pros" :key="i">{{ n }}</li>
    </ul>

    <div class="links">
      <a v-if="v.vehicle_url" :href="v.vehicle_url" target="_blank" rel="noopener">Ver anuncio ↗</a>
      <span class="off" v-if="v.stock_number">Stock {{ v.stock_number }}</span>
      <span class="off" v-if="v.vin">VIN {{ v.vin }}</span>
    </div>
  </div>
</template>

<style scoped>
.card{background:var(--card);border:1px solid var(--line);border-left-width:4px;
  border-radius:12px;padding:14px 16px;margin-bottom:12px}
.card.GREEN{border-left-color:var(--green)}
.card.YELLOW{border-left-color:var(--yellow)}
.card.RED{border-left-color:var(--red)}
.card.EXCLUDED{border-left-color:var(--grey);opacity:.82}
.top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}
.name{font-weight:650;font-size:16px;letter-spacing:-.01em;margin-top:4px}
.pricebox{text-align:right}
.price{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.drop{color:var(--green);font-size:12px;font-weight:600}
.tax{font-size:12px}
.badge{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
  padding:3px 8px;border-radius:6px}
.chip.ok{background:var(--green-bg);color:var(--green)}
.GREEN .badge{background:var(--green-bg);color:var(--green)}
.YELLOW .badge{background:var(--yellow-bg);color:var(--yellow)}
.RED .badge{background:var(--red-bg);color:var(--red)}
.EXCLUDED .badge{background:var(--grey-bg);color:var(--grey)}
.meta{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-top:9px}
.meta b{color:var(--ink);font-weight:600}
.notes{margin:10px 0 0;padding:0;list-style:none;font-size:13px}
.notes li{padding:4px 0 4px 18px;position:relative;color:var(--muted)}
.notes li::before{content:"▸";position:absolute;left:2px;color:var(--yellow)}
.pros li::before{content:"✓";color:var(--green)}
.bad li::before{content:"✕";color:var(--grey)}
.links{margin-top:11px;display:flex;gap:14px;font-size:13px;flex-wrap:wrap;align-items:center}
.spark{display:inline-flex;align-items:flex-end;gap:2px;height:16px}
.spark i{width:4px;background:var(--accent);border-radius:1px;display:block}
</style>
