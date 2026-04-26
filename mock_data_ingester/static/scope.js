const MAX_PTS  = 5000;
const WINDOW   = 500;    // points visible in rolling mode

const ts  = [];
const val = [];
let markers = [];

let following = true;    // true = rolling window, false = user is panning
let datastate = 1;

const evencolor = "#00ff88";
const oddcolor = "#0088ff";
let strokeColor = evencolor;

// ── uPlot config ──────────────────────────────────────────────────────────
const opts = {
  width:  window.innerWidth,
  height: window.innerHeight - 4,
  background: "#0a0a0a",
  scales: {
    x: { time: false },
    y: { range: [-2, 2] },
  },
  axes: [
    { stroke: "#334", grid: { stroke: "#1a1a1a" } },
    { stroke: "#334", grid: { stroke: "#1a1a1a" } },
  ],
  series: [
    {},
    {
      stroke: "#00ff88",
      width:  1.5,
      fill:   "rgba(0,255,136,0.04)",
    },
  ],
  cursor: { show: true },
  legend: { show: false },

  // Range selection → zoom
  select: { show: true },
  hooks: {
    setSelect: [u => {
      const min = u.posToVal(u.select.left, "x");
      const max = u.posToVal(u.select.left + u.select.width, "x");
      if (max > min) {
        following = false;
        u.setScale("x", { min, max });
      }
      u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
      syncScrubber();
    }],
    draw: [u => {
        markers.forEach( mt => {
            const x = Math.round(u.valToPos(mt,"x"));
            u.ctx.strokeStyle = "#000000";
            u.ctx.lineWidth = 2;
            u.ctx.beginPath();
            u.ctx.moveTo(x, u.bbox.top);
            u.ctx.lineTo(x, u.bbox.top + u.bbox.height);
            u.ctx.stroke();
        })
    }]
  },
};

const plot = new uPlot(opts, [ts, val], document.getElementById("plot"));

function syncScrubber() {
    if (!ts.length) return;

    const dataMax = ts.length ? ts[ts.length - 1] : 1;
    const dataMin = ts.length ? ts[0] : 0;
    const dataSpan = dataMax - dataMin;
    const xcenter = (plot.scales.x.min + plot.scales.x.max) / 2;
    xscrub.value = dataSpan > 0 ? (xcenter - dataMin) / dataSpan : 1;

}

window.addEventListener("resize", () => {
  plot.setSize({ width: window.innerWidth, height: window.innerHeight - 4 });
});

// -- Bar to pan 
const xscrub = document.getElementById("xscrub")
xscrub.addEventListener("input", e=>{
    const pos = parseFloat(e.target.value);
    const span = plot.scales.x.max - plot.scales.x.min;

    const dataMax = ts.length ? ts[ts.length - 1] : 1;
    const dataMin = ts.length ? ts[0] : 0;

    const min = dataMin + (dataMax - dataMin - span) * pos 
    following = (pos >= 0.999);
    if (!following) plot.setScale("x", {min, max: min + span})

})

// ── Scroll to pan / snap ──────────────────────────────────────────────────
plot.root.addEventListener("wheel", e => {
  e.preventDefault();

  const scaleX  = plot.scales.x;
  const span    = scaleX.max - scaleX.min;
  const delta   = span * 0.1 * Math.sign(e.deltaY);
  let   min     = scaleX.min + delta;
  let   max     = scaleX.max + delta;

  // Clamp to data range
  const dataMax = ts.length ? ts[ts.length - 1] : 1;
  const dataMin = ts.length ? ts[0] : 0;

  if (min < dataMin) { min = dataMin; max = dataMin + span; }
  if (max >= dataMax) {
    // Snapped back to the right edge → re-engage rolling
    following = true;
    return;
  }

  following = false;
  plot.setScale("x", { min, max });

  syncScrubber();
}, { passive: false });

// ── Double-click to reset to rolling ─────────────────────────────────────
plot.root.addEventListener("dblclick", () => {
  following = true;
});

// ── SSE data ingestion ────────────────────────────────────────────────────
new EventSource("/stream").onmessage = e => {
  const batch = JSON.parse(e.data);
  let now = ts.length ? ts[ts.length - 1] : 0;

  for (const v of batch) {
    if (v.f & (1 << 0)) {
        markers.push(v.t)
        datastate = datastate + 1;
        strokeColor = datastate % 2 ? evencolor : oddcolor;
    }
    ts.push(v.t);
    val.push(v.v);
  }

  if (ts.length > MAX_PTS) {
    ts.splice(0, ts.length - MAX_PTS);
    val.splice(0, val.length - MAX_PTS);
  }

  plot.setData([ts, val], following);

  if (following && ts.length > WINDOW) {
    const min = ts[ts.length - WINDOW];
    const max = ts[ts.length - 1];
    plot.setScale("x", { min, max });
    syncScrubber()
  }
};
