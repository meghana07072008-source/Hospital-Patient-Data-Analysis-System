/* Pulseboard - dashboard rendering (ECG trace, Chart.js charts, admin extras) */
(function () {
  'use strict';

  var dash = document.getElementById('dash');
  if (!dash) return;

  var PB = window.PB || { reduced: false, fmt: function (n) { return String(n); }, countUp: function (el, v) { el.textContent = v; } };
  var scope = dash.getAttribute('data-scope');
  var days = 365;
  var data = null;
  var charts = {};
  var loadToken = 0, traceToken = 0;
  var WEEK = { Mon: 'Monday', Tue: 'Tuesday', Wed: 'Wednesday', Thu: 'Thursday', Fri: 'Friday', Sat: 'Saturday', Sun: 'Sunday' };
  var NS = 'http://www.w3.org/2000/svg';

  function $(id) { return document.getElementById(id); }
  function css(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function fmt(n, d) { return PB.fmt(n, d); }
  function rgba(hex, a) {
    var h = (hex || '#0e7c86').replace('#', '');
    if (h.length === 3) h = h.replace(/(.)/g, '$1$1');
    var n = parseInt(h, 16);
    return 'rgba(' + (n >> 16 & 255) + ',' + (n >> 8 & 255) + ',' + (n & 255) + ',' + a + ')';
  }
  function count(el, v, d) { PB.countUp(el, v, { decimals: d || 0 }); }
  function svgEl(name, attrs) {
    var e = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    return e;
  }

  /* ---------------------------------------------------------- loading */
  function load() {
    var mine = ++loadToken;
    dash.classList.add('is-loading');
    var url = '/api/dashboard?range=' + days + (scope === 'admin' ? '&scope=admin' : '');
    fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        if (r.redirected) { window.location.href = '/login'; throw 0; }
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (d) {
        if (mine !== loadToken) return;
        data = d;
        dash.classList.remove('is-loading');
        render(d, true);
      })
      .catch(function (err) {
        if (err === 0) return;
        $('rangeNote').textContent = 'Could not load the dashboard data. Reload the page to try again.';
      });
  }

  function render(d, animate) {
    $('rangeNote').textContent = d.meta.start + ' to ' + d.meta.end + ', ' + fmt(d.meta.days) + ' days of data';
    renderKpis(d);
    renderPulse(d, animate);
    renderCharts(d, animate);
    if (d.admin) { renderFlags(d.admin.flags); renderHeat(d.admin.heatmap); }
  }

  /* ---------------------------------------------------------- KPIs */
  function renderKpis(d) {
    var k = d.kpis;
    count($('kTotal'), k.total_visits, 0);
    var tf = $('kTotalFoot');
    tf.textContent = '';
    if (k.change_vs_previous === null || k.change_vs_previous === undefined) {
      tf.textContent = fmt(k.unique_patients) + ' distinct synthetic patients';
    } else {
      var up = k.change_vs_previous >= 0;
      var s = document.createElement('span');
      s.className = 'delta' + (up ? '' : ' down');
      s.textContent = (up ? 'Up ' : 'Down ') + Math.abs(k.change_vs_previous).toFixed(1) + '%';
      tf.appendChild(s);
      tf.appendChild(document.createTextNode(' on the previous period'));
    }
    count($('kAvg'), k.avg_daily, 1);
    $('kAvgFoot').textContent = 'Median ' + fmt(k.median_daily, 1) + ', 90th percentile ' + fmt(k.p90_daily, 1);
    $('kDept').textContent = k.busiest_department;
    var top = d.departments[0];
    $('kDeptFoot').textContent = top ? fmt(top.visits) + ' visits, ' + top.share + '% of the total' : 'No visits in this range';
    $('kDay').textContent = WEEK[k.peak_weekday] || k.peak_weekday;
    $('kDayFoot').textContent = k.total_visits ? 'About ' + fmt(k.peak_weekday_avg, 1) + ' visits on an average ' + (WEEK[k.peak_weekday] || '') : 'No visits in this range';
  }

  /* ---------------------------------------------------------- ECG trace */
  function stats(values) {
    var a = values.slice().sort(function (x, y) { return x - y; });
    var n = a.length;
    if (!n) return { median: 0, p90: 0, std: 0 };
    function q(p) { var i = (n - 1) * p, lo = Math.floor(i), hi = Math.ceil(i); return a[lo] + (a[hi] - a[lo]) * (i - lo); }
    var mean = a.reduce(function (s, v) { return s + v; }, 0) / n;
    var sd = Math.sqrt(a.reduce(function (s, v) { return s + (v - mean) * (v - mean); }, 0) / n);
    return { median: q(0.5), p90: q(0.9), std: sd };
  }

  function renderPulse(d, animate) {
    var p = d.pulse;
    count($('pulseAvg'), p.avg, 1);
    var peak = $('pulsePeak');
    peak.textContent = '';
    if (p.values.length) {
      peak.appendChild(document.createTextNode('Busiest day: '));
      var b = document.createElement('b');
      b.textContent = p.peak_label;
      peak.appendChild(b);
      peak.appendChild(document.createTextNode(' with ' + fmt(p.peak_value) + ' visits'));
    }
    var st = stats(p.values);
    $('stMedian').textContent = fmt(st.median, 1);
    $('stP90').textContent = fmt(st.p90, 1);
    $('stStd').textContent = '±' + fmt(st.std, 1);
    drawTrace(p, animate);
  }

  function drawTrace(p, animate) {
    var box = $('pulseTrace'), svg = $('pulseSvg'), tip = $('pulseTip');
    var W = box.clientWidth, H = box.clientHeight;
    var mine = ++traceToken;
    if (!W || !H) return;
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    tip.hidden = true;
    var vals = p.values, n = vals.length;
    if (!n) return;

    var padX = 8, padT = 30, padB = 24;
    var base = padT + (H - padT - padB) * 0.68;
    var maxA = base - padT;
    var vmax = Math.max.apply(null, vals), vmin = Math.min.apply(null, vals);
    var span = vmax - vmin || 1;
    var bw = (W - padX * 2) / n;
    var amps = vals.map(function (v) { return (0.3 + 0.7 * ((v - vmin) / span)) * maxA; });

    var dstr = 'M' + padX + ' ' + base;
    amps.forEach(function (a, i) {
      var x = padX + i * bw;
      function px(f) { return (x + bw * f).toFixed(1); }
      function y(v) { return v.toFixed(1); }
      dstr += ' L' + px(0.10) + ' ' + y(base) +
        ' Q' + px(0.15) + ' ' + y(base - a * 0.14) + ' ' + px(0.20) + ' ' + y(base) +
        ' L' + px(0.30) + ' ' + y(base) +
        ' L' + px(0.34) + ' ' + y(base + a * 0.10) +
        ' L' + px(0.40) + ' ' + y(base - a) +
        ' L' + px(0.46) + ' ' + y(base + a * 0.26) +
        ' L' + px(0.52) + ' ' + y(base) +
        ' Q' + px(0.64) + ' ' + y(base - a * 0.30) + ' ' + px(0.76) + ' ' + y(base) +
        ' L' + px(1) + ' ' + y(base);
    });

    svg.appendChild(svgEl('line', { x1: padX, x2: W - padX, y1: base, y2: base, 'class': 'pulse-base' }));
    var path = svgEl('path', { d: dstr, 'class': 'pulse-line' });
    svg.appendChild(path);

    var peakIdx = vals.indexOf(vmax);
    var peakDot = svgEl('circle', { cx: padX + peakIdx * bw + bw * 0.40, cy: base - amps[peakIdx], r: 5.5, 'class': 'pulse-peakdot' });
    var head = svgEl('circle', { cx: padX, cy: base, r: 4.5, 'class': 'pulse-head' });
    var hover = svgEl('circle', { cx: 0, cy: 0, r: 5.5, 'class': 'pulse-hover' });
    svg.appendChild(peakDot);
    svg.appendChild(hover);
    svg.appendChild(head);

    vals.forEach(function (v, i) {
      var hit = svgEl('rect', { x: padX + i * bw, y: 0, width: bw, height: H, 'class': 'pulse-hit' });
      function show() {
        var cx = padX + i * bw + bw * 0.40, cy = base - amps[i];
        hover.setAttribute('cx', cx); hover.setAttribute('cy', cy); hover.style.opacity = 1;
        tip.textContent = '';
        var s = document.createElement('span'); s.textContent = fmt(v) + ' visits';
        var sm = document.createElement('small'); sm.textContent = p.labels[i];
        tip.appendChild(s); tip.appendChild(sm);
        tip.style.left = Math.min(Math.max(cx, 56), W - 56) + 'px';
        tip.style.top = cy + 'px';
        tip.hidden = false;
      }
      function hide() { hover.style.opacity = 0; tip.hidden = true; }
      hit.addEventListener('pointerenter', show);
      hit.addEventListener('pointerleave', hide);
      svg.appendChild(hit);
    });

    if (!animate || PB.reduced) {
      head.style.opacity = 0; peakDot.style.opacity = 1; return;
    }
    var len = path.getTotalLength(), t0 = null, dur = 2600;
    path.style.strokeDasharray = len;
    path.style.strokeDashoffset = len;
    function step(ts) {
      if (mine !== traceToken) return;
      if (t0 === null) t0 = ts;
      var t = Math.min((ts - t0) / dur, 1);
      var e = 1 - Math.pow(1 - t, 3);
      path.style.strokeDashoffset = len * (1 - e);
      var pt = path.getPointAtLength(len * e);
      head.setAttribute('cx', pt.x); head.setAttribute('cy', pt.y);
      if (t < 1) { requestAnimationFrame(step); }
      else { head.style.opacity = 0; peakDot.style.opacity = 1; path.style.strokeDasharray = 'none'; }
    }
    requestAnimationFrame(step);
  }

  /* ---------------------------------------------------------- charts */
  var valueLabels = {
    id: 'valueLabels',
    afterDatasetsDraw: function (chart, args, o) {
      if (!o || !o.show) return;
      var ctx = chart.ctx, ds = o.dataset || 0;
      var meta = chart.getDatasetMeta(ds);
      if (meta.hidden) return;
      ctx.save();
      ctx.font = '600 11.5px Figtree, system-ui, sans-serif';
      ctx.fillStyle = css('--ink-2');
      meta.data.forEach(function (bar, i) {
        var v = chart.data.datasets[ds].data[i];
        var txt = o.format ? o.format(v, i) : fmt(v);
        if (chart.options.indexAxis === 'y') { ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(txt, bar.x + 7, bar.y); }
        else { ctx.textAlign = 'center'; ctx.textBaseline = 'bottom'; ctx.fillText(txt, bar.x, bar.y - 5); }
      });
      ctx.restore();
    }
  };
  var centerText = {
    id: 'centerText',
    afterDraw: function (chart, args, o) {
      if (!o || !o.title) return;
      var a = chart.chartArea, ctx = chart.ctx, cx = (a.left + a.right) / 2, cy = (a.top + a.bottom) / 2;
      ctx.save();
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillStyle = css('--ink');
      ctx.font = '700 26px "Bricolage Grotesque", system-ui, sans-serif';
      ctx.fillText(o.title, cx, cy - 8);
      ctx.fillStyle = css('--muted');
      ctx.font = '500 12.5px Figtree, system-ui, sans-serif';
      ctx.fillText(o.sub || '', cx, cy + 15);
      ctx.restore();
    }
  };
  if (window.Chart) { Chart.register(valueLabels, centerText); }

  function baseOptions(animate, extra) {
    var o = {
      responsive: true,
      maintainAspectRatio: false,
      animation: (animate && !PB.reduced) ? {
        duration: 1100, easing: 'easeOutQuart',
        delay: function (c) { return c.type === 'data' && c.mode === 'default' ? c.dataIndex * 55 : 0; }
      } : false,
      layout: { padding: { top: 18, right: 10 } },
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: '#0b2a33', titleColor: '#ffffff', bodyColor: '#d6ebee', padding: 11, cornerRadius: 9, displayColors: false, titleFont: { weight: '600' } }
      }
    };
    Object.keys(extra || {}).forEach(function (k) {
      if (k === 'plugins') Object.keys(extra.plugins).forEach(function (p) { o.plugins[p] = extra.plugins[p]; });
      else if (k === 'layout') o.layout = extra.layout;
      else o[k] = extra[k];
    });
    return o;
  }
  function axes(horizontal) {
    var grid = { color: css('--line'), drawTicks: false }, none = { display: false };
    var tick = { color: css('--muted'), padding: 8 };
    var val = { beginAtZero: true, grid: grid, border: none, ticks: tick };
    var cat = { grid: none, border: { color: css('--line-strong') }, ticks: { color: css('--ink-2'), padding: 8 } };
    return horizontal ? { x: val, y: cat } : { x: cat, y: val };
  }
  function make(id, cfg) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart($(id), cfg);
  }

  function renderCharts(d, animate) {
    if (!window.Chart) { useFallbackImages(); return; }
    Chart.defaults.font.family = 'Figtree, system-ui, sans-serif';
    Chart.defaults.font.size = 12;
    Chart.defaults.color = css('--muted');
    var teal = css('--teal'), aqua = css('--aqua'), coral = css('--coral'), amber = css('--amber'), ink = css('--ink'), surface = css('--surface');

    var m = d.monthly;
    make('chMonthly', {
      type: 'bar',
      data: {
        labels: m.labels,
        datasets: [
          { type: 'bar', label: 'Visits', data: m.values, order: 2, borderRadius: 8, borderSkipped: false, maxBarThickness: 46,
            backgroundColor: m.partial.map(function (p) { return p ? rgba(aqua, 0.55) : teal; }) },
          { type: 'line', label: 'Trend', data: m.values, order: 1, borderColor: ink, borderWidth: 2, tension: 0.35, pointRadius: 3.5,
            pointBackgroundColor: surface, pointBorderColor: ink, pointBorderWidth: 2 }
        ]
      },
      options: baseOptions(animate, {
        scales: axes(false),
        plugins: { tooltip: { backgroundColor: '#0b2a33', padding: 11, cornerRadius: 9, displayColors: false,
          filter: function (item) { return item.datasetIndex === 0; },
          callbacks: { label: function (c) { return fmt(c.parsed.y) + ' visits'; } } } }
      })
    });

    var dp = d.departments;
    make('chDepts', {
      type: 'bar',
      data: {
        labels: dp.map(function (x) { return x.name; }),
        datasets: [{ data: dp.map(function (x) { return x.visits; }), borderRadius: 7, borderSkipped: false, barPercentage: 0.74,
          backgroundColor: dp.map(function (x) { return x.name === 'Emergency Medicine' ? coral : teal; }) }]
      },
      options: baseOptions(animate, {
        indexAxis: 'y',
        layout: { padding: { top: 6, right: 56 } },
        scales: axes(true),
        plugins: {
          valueLabels: { show: true },
          tooltip: { backgroundColor: '#0b2a33', padding: 11, cornerRadius: 9, displayColors: false,
            callbacks: { label: function (c) { var x = dp[c.dataIndex]; return fmt(x.visits) + ' visits, ' + x.share + '% of total, ' + x.avg_per_day + ' per day'; } } }
        }
      })
    });

    var ag = d.age_bands;
    make('chAges', {
      type: 'bar',
      data: { labels: ag.labels, datasets: [{ data: ag.values, borderRadius: 8, borderSkipped: false, maxBarThickness: 44, backgroundColor: teal }] },
      options: baseOptions(animate, {
        scales: axes(false),
        plugins: {
          valueLabels: { show: true, format: function (v, i) { return ag.suppressed[i] ? '<5' : fmt(v); } },
          tooltip: { backgroundColor: '#0b2a33', padding: 11, cornerRadius: 9, displayColors: false,
            callbacks: { label: function (c) { return ag.suppressed[c.dataIndex] ? 'Fewer than 5 visits (hidden)' : fmt(c.parsed.y) + ' visits, ' + ag.shares[c.dataIndex] + '%'; } } }
        }
      })
    });

    var wk = d.weekday;
    make('chWeek', {
      type: 'bar',
      data: { labels: wk.labels, datasets: [{ data: wk.values, borderRadius: 8, borderSkipped: false, maxBarThickness: 44,
        backgroundColor: wk.values.map(function (v, i) { return i >= 5 ? coral : teal; }) }] },
      options: baseOptions(animate, {
        scales: axes(false),
        plugins: {
          valueLabels: { show: true, format: function (v) { return fmt(v, 1); } },
          tooltip: { backgroundColor: '#0b2a33', padding: 11, cornerRadius: 9, displayColors: false,
            callbacks: { label: function (c) { return fmt(c.parsed.y, 1) + ' visits per day on average'; } } }
        }
      })
    });

    var vt = d.visit_types, total = vt.values.reduce(function (s, v) { return s + v; }, 0);
    make('chTypes', {
      type: 'doughnut',
      data: { labels: vt.labels, datasets: [{ data: vt.values, backgroundColor: [teal, aqua, amber, coral], borderColor: surface, borderWidth: 3, hoverOffset: 6 }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '68%',
        animation: (animate && !PB.reduced) ? { duration: 1300, easing: 'easeOutQuart' } : false,
        layout: { padding: { top: 4, bottom: 4 } },
        plugins: {
          legend: { position: 'bottom', labels: { usePointStyle: true, pointStyle: 'circle', boxWidth: 8, padding: 14, color: css('--ink-2') } },
          tooltip: { backgroundColor: '#0b2a33', padding: 11, cornerRadius: 9, displayColors: false,
            callbacks: { label: function (c) { return fmt(c.parsed) + ' visits, ' + vt.shares[c.dataIndex] + '%'; } } },
          centerText: { title: total >= 10000 ? fmt(total / 1000, 1) + 'k' : fmt(total), sub: 'visits' }
        }
      }
    });
  }

  function useFallbackImages() {
    Array.prototype.forEach.call(document.querySelectorAll('canvas[data-fallback]'), function (cv) {
      var img = document.createElement('img');
      img.alt = 'Chart (static version)';
      img.src = '/chart/' + cv.getAttribute('data-fallback') + '.png?range=' + days;
      cv.parentNode.replaceChild(img, cv);
    });
  }

  /* ---------------------------------------------------------- admin extras */
  function renderFlags(list) {
    var ul = $('flags');
    if (!ul) return;
    ul.textContent = '';
    if (!list.length) { var li0 = document.createElement('li'); li0.className = 'empty'; li0.textContent = 'Not enough history to compare yet.'; ul.appendChild(li0); return; }
    list.forEach(function (f, i) {
      var li = document.createElement('li');
      li.className = 'flag';
      li.style.setProperty('--i', i);
      var name = document.createElement('span'); name.className = 'flag-name'; name.textContent = f.department;
      var badge = document.createElement('span'); badge.className = 'flag-badge ' + f.status; badge.textContent = f.status;
      var track = document.createElement('span'); track.className = 'flag-track';
      var fill = document.createElement('span');
      fill.className = 'flag-fill ' + (f.change_pct >= 0 ? 'pos' : 'neg');
      fill.style.width = Math.min(Math.abs(f.change_pct) / 40, 1) * 50 + '%';
      track.appendChild(fill);
      var pct = document.createElement('span'); pct.className = 'flag-pct';
      pct.textContent = (f.change_pct > 0 ? '+' : '') + f.change_pct.toFixed(1) + '%';
      pct.title = 'Last 30 days: ' + f.recent_avg + ' per day. Previous 90 days: ' + f.baseline_avg + ' per day.';
      [name, badge, track, pct].forEach(function (e) { li.appendChild(e); });
      ul.appendChild(li);
    });
  }

  function renderHeat(h) {
    var g = $('heat');
    if (!g) return;
    g.textContent = '';
    if (!h.departments.length) { g.textContent = 'No visits in this range.'; return; }
    function cell(text, cls) { var e = document.createElement('div'); e.className = cls; e.textContent = text; return e; }
    g.appendChild(cell('', 'heat-head'));
    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach(function (w) { g.appendChild(cell(w, 'heat-head')); });
    h.departments.forEach(function (dep, r) {
      g.appendChild(cell(dep, 'heat-label'));
      h.values[r].forEach(function (v, c) {
        var ratio = h.max ? v / h.max : 0;
        var e = cell(fmt(v, 1), 'heat-cell' + (ratio > 0.55 ? ' hot' : ''));
        e.style.setProperty('--h', ratio.toFixed(3));
        e.style.setProperty('--d', r + c);
        e.title = dep + ', ' + ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][c] + ': ' + fmt(v, 1) + ' visits per day';
        g.appendChild(e);
      });
    });
  }

  /* ---------------------------------------------------------- events */
  Array.prototype.forEach.call(document.querySelectorAll('.seg-btn'), function (btn) {
    btn.addEventListener('click', function () {
      if (btn.classList.contains('on')) return;
      Array.prototype.forEach.call(document.querySelectorAll('.seg-btn'), function (b) { b.classList.remove('on'); });
      btn.classList.add('on');
      days = parseInt(btn.getAttribute('data-days'), 10);
      load();
    });
  });
  document.addEventListener('themechange', function () { if (data) renderCharts(data, false); });
  var resizeTimer;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { if (data) drawTrace(data.pulse, false); }, 160);
  });

  load();
})();
