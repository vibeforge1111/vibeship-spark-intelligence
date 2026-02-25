async function loadJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Failed: ${path}`);
  return await res.json();
}

function pctFromProgress(base, target) {
  if (typeof base !== 'number' || typeof target !== 'number') return 0;
  if (base === target) return 100;
  const improvingDown = target < base;
  return Math.max(0, Math.min(100, improvingDown ? 100 - ((target / base) * 100) : ((base / target) * 100)));
}

function metricCard(k) {
  const progress = pctFromProgress(k.baseline, k.target);
  return `
    <article class="kpi-card">
      <div class="kpi-key">${k.key}</div>
      <div class="bar"><div class="fill" style="width:${progress}%"></div></div>
      <div class="kpi-values">
        <span>base: <b>${k.baseline}</b></span>
        <span>target: <b>${k.target}</b></span>
      </div>
    </article>
  `;
}

function taskCard(t) {
  return `
    <article class="task">
      <div class="title">${t.id} — ${t.task}</div>
      <div class="intent">${t.intent || ''}</div>
      <div class="kpi">KPI: ${t.kpi || 'n/a'}${t.baseline !== undefined ? ` | ${t.baseline} -> ${t.target}` : ''}</div>
      <div class="meta">
        <span class="${(t.priority||'').toLowerCase()==='p0'?'prio-p0':'prio-p1'}">${t.priority || ''}</span>
        <span>Impact ${t.impact ?? '-'}</span>
        <span>Urgency ${t.urgency ?? '-'}</span>
        <span>Risk ${t.risk_reduction ?? t.riskReduction ?? '-'}</span>
        <span>Effort ${t.effort ?? '-'}</span>
        <span class="score">Score ${t.priority_score ?? '-'}</span>
      </div>
    </article>
  `;
}

function renderAnalytics(board) {
  const cols = board.columns;
  const all = Object.values(cols).flat();
  const inProgress = cols.in_progress.length;
  const ready = cols.ready.length;
  const backlog = cols.backlog.length;
  const blocked = cols.blocked.length;
  const done = cols.done.length;
  const avgScore = all.filter(x=>typeof x.priority_score==='number').reduce((a,b)=>a+b.priority_score,0) /
    Math.max(1, all.filter(x=>typeof x.priority_score==='number').length);

  const cards = [
    ['Total Cards', all.length],
    ['In Progress', inProgress],
    ['Ready', ready],
    ['Backlog', backlog],
    ['Blocked', blocked],
    ['Done', done],
    ['Avg Priority Score', avgScore.toFixed(2)]
  ];

  document.getElementById('analyticsGrid').innerHTML = cards.map(([k,v]) =>
    `<article class="analytics-card"><div class="kpi-key">${k}</div><div><b>${v}</b></div></article>`
  ).join('');
}

function renderBoard(board) {
  const columns = [
    ['in_progress','IN_PROGRESS'],
    ['ready','READY'],
    ['backlog','BACKLOG'],
    ['blocked','BLOCKED'],
    ['done','DONE']
  ];

  document.getElementById('board').innerHTML = columns.map(([key,label]) => {
    const tasks = (board.columns[key] || []).slice().sort((a,b)=>(b.priority_score||0)-(a.priority_score||0));
    return `
      <section class="col">
        <h3>${label} <span class="badge">${tasks.length}</span></h3>
        <div class="task-list">
          ${tasks.map(taskCard).join('') || '<div class="muted">No tasks</div>'}
        </div>
      </section>
    `;
  }).join('');

  const top = Object.values(board.columns).flat()
    .filter(t => typeof t.priority_score === 'number')
    .sort((a,b)=>b.priority_score-a.priority_score)
    .slice(0,10);
  document.getElementById('topTasks').innerHTML = top.map(taskCard).join('');
}

function renderQuestions(q) {
  const all = q.tasks || [];
  document.getElementById('questionBacklog').innerHTML = all
    .sort((a,b)=>(b.priority_score||0)-(a.priority_score||0))
    .map(taskCard)
    .join('');
}

(async function init() {
  try {
    const [board, questions] = await Promise.all([
      loadJson('data/board.json'),
      loadJson('data/questions_backlog.json')
    ]);

    document.getElementById('updatedAt').textContent = `Updated: ${board.updated_at}`;
    document.getElementById('kpiGrid').innerHTML = (board.kpis || []).map(metricCard).join('');

    renderAnalytics(board);
    renderBoard(board);
    renderQuestions(questions);
  } catch (err) {
    document.body.innerHTML = `<pre style="padding:16px;color:#ff9aa5">Dashboard load error: ${err.message}</pre>`;
  }
})();
