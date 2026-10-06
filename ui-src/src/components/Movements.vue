<script setup>
import { computed } from 'vue'

const props = defineProps({ m: Object })

const money = n => n == null ? '—' : '$' + Number(n).toLocaleString('en-CA')
const days = props.m?.observing_days ?? 0
const dayTxt = computed(() => days < 1 ? 'menos de un día'
  : days < 2 ? '1 día' : `${Math.round(days)} días`)

const rot = computed(() => (props.m?.rotation || []).filter(r => r.n_gone_all >= 3))
const watching = computed(() =>
  (props.m?.rotation || []).reduce((a, r) => a + r.still_here, 0))
const relists = computed(() => props.m?.relists || [])
const swings = computed(() => props.m?.swings || [])
const s = computed(() => props.m?.summary || {})

const arrow = n => n == null ? '' : n > 0 ? `+${money(n).slice(1)}` : `−${money(-n).slice(1)}`
</script>

<template>
  <div class="mv">
    <!-- lo que pasó, en cuatro números -->
    <div class="kpis">
      <div class="kpi"><b>{{ s.new }}</b><span>llegaron</span></div>
      <div class="kpi"><b>{{ s.gone }}</b><span>se fueron</span></div>
      <div class="kpi"><b>{{ s.drop }}</b><span>bajaron de precio</span></div>
      <div class="kpi"><b>{{ s.up }}</b><span>subieron</span></div>
      <div class="kpi-note">últimos {{ s.days }} días · sin contar los {{ s.seeded }} del primer barrido</div>
    </div>

    <!-- ¿vuelan o se quedan parados? -->
    <h3>⏱️ ¿Cuánto aguantan en el lote?</h3>
    <p class="lead">
      Si los autos de tu rango se van mucho más rápido que el resto, hay que llamar el mismo día.
      Si se quedan parados, tienes margen para esperar una bajada.
      Solo cuentan los que <b>vimos llegar</b>: de los que ya estaban ahí no sabemos cuándo se publicaron.
    </p>

    <div v-if="rot.length" class="tablewrap">
      <table>
        <thead><tr><th>Concesionaria</th><th class="num">Los tuyos</th><th class="num">Todos</th><th>Lectura</th></tr></thead>
        <tbody>
          <tr v-for="r in rot" :key="r.dealer_id">
            <td>{{ r.name }}</td>
            <td class="num"><b v-if="r.median_days_hit != null">{{ r.median_days_hit }} d</b><span v-else class="off">—</span></td>
            <td class="num">{{ r.median_days_all != null ? r.median_days_all + ' d' : '—' }}</td>
            <td class="off">{{ r.read || `solo ${r.n_gone_hit} de los tuyos se han ido; aún no dice nada` }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty small">
      Llevo <b>{{ dayTxt }}</b> mirando y sigo <b>{{ watching }}</b> autos desde que aparecieron.
      Para saber cuánto duran hace falta verlos irse: esto se llena solo, en dos o tres semanas.
    </div>

    <!-- el mismo auto, otra vez -->
    <h3>🔁 El mismo auto, subido otra vez</h3>
    <p class="lead">
      Se identifica por el <b>VIN</b>, así que es el mismo coche de verdad, no uno parecido.
      Un lote que quita y vuelve a poner el mismo auto está tanteando: ese precio no es firme.
    </p>
    <div v-if="relists.length">
      <div v-for="(r, i) in relists" :key="i" class="mrow">
        <span class="tag">{{ r.kind }}</span>
        <b>{{ r.what }}</b>
        <span class="off">· {{ r.dealer }}</span>
        <span v-if="r.old_price && r.new_price">
          · {{ money(r.old_price) }} → {{ money(r.new_price) }}
          <b :class="r.delta < 0 ? 'good' : 'bad'" v-if="r.delta">{{ arrow(r.delta) }}</b>
        </span>
        <span v-else-if="r.new_price" class="off">· {{ money(r.new_price) }}</span>
        <span v-if="r.days_off != null" class="off">· fuera {{ r.days_off }} d</span>
        <a v-if="r.url" :href="r.url" target="_blank" rel="noopener">ver ↗</a>
      </div>
    </div>
    <div v-else class="empty small">
      Ninguno todavía. Aparecerá aquí en cuanto un lote borre un anuncio y vuelva a subir el mismo VIN.
    </div>

    <!-- precios que van y vienen -->
    <h3>🎢 Precios que suben y bajan</h3>
    <p class="lead">
      No es una rebaja: es un precio que se ha movido en las <b>dos</b> direcciones.
      Significa que el número del anuncio es una opinión del vendedor, no un valor fijo.
    </p>
    <div v-if="swings.length">
      <div v-for="(r, i) in swings" :key="i" class="mrow">
        <b>{{ r.what }}</b>
        <span class="off">· {{ r.dealer }}</span>
        <span class="series">{{ r.series.map(money).join(' → ') }}</span>
        <b :class="r.net < 0 ? 'good' : 'bad'">{{ arrow(r.net) }}</b>
        <span v-if="r.gone" class="off">· ya no figura</span>
        <a v-if="r.url" :href="r.url" target="_blank" rel="noopener">ver ↗</a>
      </div>
    </div>
    <div v-else class="empty small">
      Nada aún: hace falta ver al menos tres precios distintos del mismo auto.
    </div>
  </div>
</template>

<style scoped>
.mv h3{font-size:13px;font-weight:700;margin:26px 0 6px;color:var(--ink);letter-spacing:-.01em}
.mv h3:first-of-type{margin-top:22px}
.lead{margin:0 0 12px;font-size:12.5px;color:var(--muted);line-height:1.6;max-width:78ch}

.kpis{display:flex;gap:10px;flex-wrap:wrap;align-items:stretch}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:10px 16px;min-width:104px}
.kpi b{display:block;font-size:22px;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.kpi span{font-size:11.5px;color:var(--muted)}
.kpi-note{align-self:center;font-size:11.5px;color:var(--muted);max-width:190px;line-height:1.45}

.mrow{font-size:13px;padding:7px 0;border-bottom:1px solid var(--line);
  display:flex;gap:7px;flex-wrap:wrap;align-items:baseline}
.mrow:last-child{border-bottom:none}
.tag{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
  background:var(--grey-bg);color:var(--grey);padding:2px 7px;border-radius:5px}
.series{font-variant-numeric:tabular-nums;color:var(--muted)}
.good{color:var(--green)}
.bad{color:var(--red)}
.empty.small{padding:14px 16px;text-align:left;font-size:13px;line-height:1.6}
</style>
