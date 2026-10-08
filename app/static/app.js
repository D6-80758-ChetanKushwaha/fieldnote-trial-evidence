const $ = (id) => document.getElementById(id);
const selected = new Set();
let allTrials = [];
let visibleTrials = [];
let currentPage = 1;
const pageSize = 12;
let filterRequest = 0;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function json(url, options) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}

function yieldText(value) { return value == null ? '—' : `${Number(value).toFixed(2)} t/ha`; }
function effectText(trial) {
  if (trial.status === 'conflicting') return 'Conflicting yields';
  if (trial.status === 'incomplete') return 'Incomplete data';
  return `${trial.increase_pct > 0 ? '+' : ''}${trial.increase_pct}%`;
}
function statusLabel(status) {
  return {consistent:'Consistent sources', conflicting:'Needs review', incomplete:'Missing value'}[status] || status;
}
function updateSelection() {
  $('selectedCount').textContent = `(${selected.size})`;
  $('compareButton').disabled = selected.size < 2;
}

function renderTrials(trials) {
  visibleTrials = trials;
  currentPage = 1;
  renderTrialPage();
}

function renderTrialPage() {
  const list = $('trialList');
  list.replaceChildren();
  $('resultCount').textContent = visibleTrials.length;
  $('pagination').classList.toggle('hidden', visibleTrials.length <= pageSize);
  if (!visibleTrials.length) {
    list.append(element('div', 'empty-state', 'No trials match these filters. Try a wider search.'));
    return;
  }
  const first = (currentPage - 1) * pageSize;
  const last = Math.min(first + pageSize, visibleTrials.length);
  $('pageInfo').textContent = `${first + 1}–${last} of ${visibleTrials.length}`;
  $('previousPage').disabled = currentPage === 1;
  $('nextPage').disabled = last === visibleTrials.length;
  for (const trial of visibleTrials.slice(first, last)) {
    const card = element('article', 'trial-card');
    const checkbox = element('input');
    checkbox.type = 'checkbox'; checkbox.checked = selected.has(trial.trial_id);
    checkbox.setAttribute('aria-label', `Select ${trial.trial_id} for comparison`);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) selected.add(trial.trial_id); else selected.delete(trial.trial_id);
      updateSelection();
    });
    const open = element('button', 'card-open');
    open.type = 'button'; open.addEventListener('click', () => showTrial(trial.trial_id));
    open.append(element('span', 'trial-id', trial.trial_id));
    open.append(element('h3', '', `${trial.product} · ${trial.crop}`));
    const meta = element('div', 'trial-meta');
    for (const value of [trial.country, trial.year, trial.trial_type]) meta.append(element('span', '', value));
    open.append(meta);
    const result = element('div', 'trial-result');
    result.append(element('strong', '', effectText(trial)));
    result.append(element('small', '', trial.status === 'consistent' ? 'yield difference' : 'result status'));
    result.append(element('span', `status-pill ${trial.status}`, statusLabel(trial.status)));
    card.append(checkbox, open, result); list.append(card);
  }
}

function changePage(direction) {
  const nextPage = currentPage + direction;
  if (nextPage < 1 || (nextPage - 1) * pageSize >= visibleTrials.length) return;
  currentPage = nextPage;
  renderTrialPage();
  $('trialList').scrollIntoView({behavior:'smooth',block:'start'});
}

async function loadTrials() {
  const request = ++filterRequest;
  const params = new URLSearchParams();
  const mapping = {trialId:'trial_id',crop:'crop',product:'product',country:'country',trialType:'trial_type',yearFrom:'year_from',yearTo:'year_to'};
  for (const [id, key] of Object.entries(mapping)) if ($(id).value) params.set(key, $(id).value);
  try {
    const trials = (await json(`/api/trials?${params}`)).trials;
    if (request === filterRequest) renderTrials(trials);
  } catch (error) {
    if (request === filterRequest) $('trialList').replaceChildren(element('div','empty-state',error.message));
  }
}

function sourceCard(observation) {
  const card = element('div', 'source-card');
  const link = element('a', '', `${observation.source} ↗`);
  link.href = `/api/sources/${encodeURIComponent(observation.source)}`;
  link.target = '_blank'; link.rel = 'noopener noreferrer';
  card.append(link, element('div','trial-meta', observation.location));
  card.append(element('div','source-yields',`Treated ${yieldText(observation.treated_yield_t_ha)} · Control ${yieldText(observation.control_yield_t_ha)}`));
  card.append(element('p','',observation.excerpt));
  return card;
}

async function showTrial(id) {
  const trial = await json(`/api/trials/${encodeURIComponent(id)}`);
  const panel = $('detailPanel'); panel.replaceChildren(); panel.classList.remove('hidden');
  const header = element('div','detail-header');
  const title = element('div');
  title.append(element('span','section-kicker',`${trial.trial_id} / RECORD DETAIL`));
  title.append(element('h2','',`${trial.product} · ${trial.crop}`));
  title.append(element('div','trial-meta',`${trial.country} · ${trial.year} · ${trial.trial_type}`));
  const close = element('button','close-button','Close ×'); close.onclick = () => panel.classList.add('hidden');
  header.append(title,close); panel.append(header);
  const grid = element('div','detail-grid');
  for (const [label,value] of [
    ['Treated yield',yieldText(trial.treated_yield_t_ha)],
    ['Control yield',yieldText(trial.control_yield_t_ha)],
    ['Difference',trial.increase_t_ha == null ? '—' : `${trial.increase_t_ha > 0 ? '+' : ''}${trial.increase_t_ha} t/ha`],
    ['Relative change',effectText(trial)]
  ]) { const metric=element('div','metric'); metric.append(element('span','',label),element('strong','',value)); grid.append(metric); }
  panel.append(grid);
  for (const warning of trial.warnings) panel.append(element('div','warning',warning));
  panel.append(element('h3','',`Original observations (${trial.observations.length})`));
  const sources = element('div','source-grid');
  for (const observation of trial.observations) sources.append(sourceCard(observation));
  panel.append(sources); panel.scrollIntoView({behavior:'smooth',block:'start'});
}

async function compareSelected() {
  const data = await json('/api/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({trial_ids:[...selected]})});
  const panel = $('comparePanel'); panel.replaceChildren(); panel.classList.remove('hidden');
  const header = element('div','detail-header');
  const title = element('div'); title.append(element('span','section-kicker','03 / COMPARE')); title.append(element('h2','','Side-by-side results'));
  const close = element('button','close-button','Close ×'); close.onclick=()=>panel.classList.add('hidden');
  header.append(title,close); panel.append(header);
  const table = element('table','compare-table');
  const headers = ['Trial','Product / crop','Country','Year','Type','Treated','Control','Change','Status'];
  const head = element('thead'); const row = element('tr');
  for (const label of headers) row.append(element('th','',label)); head.append(row); table.append(head);
  const body = element('tbody');
  for (const trial of data.trials) {
    const tr=element('tr'); const idCell=element('td');
    const link=element('a','',trial.trial_id); link.href=`#${trial.trial_id}`;
    link.onclick=(event)=>{event.preventDefault();showTrial(trial.trial_id);}; idCell.append(link); tr.append(idCell);
    for (const value of [`${trial.product} / ${trial.crop}`,trial.country,trial.year,trial.trial_type,yieldText(trial.treated_yield_t_ha),yieldText(trial.control_yield_t_ha),effectText(trial),statusLabel(trial.status)]) tr.append(element('td','',value));
    body.append(tr);
  }
  table.append(body); panel.append(table);
  panel.append(element('p','trial-meta','Differences are descriptive. The supplied sources do not establish statistical significance. Conflicting or incomplete trials have no calculated effect.'));
  panel.scrollIntoView({behavior:'smooth',block:'start'});
}

function renderAnswer(text) {
  const body = $('answerText');
  body.replaceChildren();
  let paragraph = [];
  let list = null;
  const flushParagraph = () => {
    if (paragraph.length) body.append(element('p', '', paragraph.join(' ')));
    paragraph = [];
  };
  for (const rawLine of text.replace(/\r\n/g, '\n').split('\n')) {
    const line = rawLine.trim();
    if (!line) { flushParagraph(); list = null; continue; }
    const listMatch = line.match(/^(?:([-*])|(\d+)[.)])\s+(.+)$/);
    if (listMatch) {
      flushParagraph();
      const tag = listMatch[2] ? 'ol' : 'ul';
      if (!list || list.tagName.toLowerCase() !== tag) {
        list = element(tag); body.append(list);
      }
      list.append(element('li', '', listMatch[3]));
      continue;
    }
    const heading = line.match(/^#{1,3}\s+(.+)$/);
    if (heading || (line.endsWith(':') && line.length < 75)) {
      flushParagraph(); list = null;
      body.append(element('h3', '', heading ? heading[1] : line.slice(0, -1)));
      continue;
    }
    list = null;
    paragraph.push(line);
  }
  flushParagraph();
}

async function readAgentStream(question, onEvent) {
  const response = await fetch('/api/agent/stream', {
    method:'POST', headers:{'Content-Type':'application/json','Accept':'text/event-stream'},
    body:JSON.stringify({question})
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || `Request failed (${response.status})`);
  }
  if (!response.body) throw new Error('This browser cannot read the live agent stream.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const {done,value} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value,{stream:true});
    let boundary;
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0,boundary);
      buffer = buffer.slice(boundary+2);
      const data = frame.split('\n').filter(line=>line.startsWith('data: ')).map(line=>line.slice(6)).join('\n');
      if (data) onEvent(JSON.parse(data));
    }
  }
}

function showAnswerSources(sources) {
  $('answerSources').replaceChildren();
  if (!sources.length) return;
  $('answerSources').append(element('strong','','Original sources'));
  for (const source of sources) {
    const link=element('a','',`${source} ↗`);
    link.href=`/api/sources/${encodeURIComponent(source)}`;
    link.target='_blank'; link.rel='noopener noreferrer';
    $('answerSources').append(link);
  }
}

function toolLabel(name) {
  return {search_trials:'Search trials',get_trial:'Inspect trial',read_source:'Read source',compare_trials:'Compare trials'}[name] || name;
}

function formatToolOutput(content) {
  try { return JSON.stringify(JSON.parse(content),null,2); }
  catch { return content; }
}

async function askQuestion(event) {
  event.preventDefault();
  const question=$('question').value.trim(); if (question.length<3) return;
  const button=$('askButton'); button.disabled=true; button.firstChild.textContent='Working… ';
  $('answerPanel').classList.remove('hidden');
  $('agentLoading').classList.remove('hidden');
  $('runStatus').textContent='working';
  $('progressText').textContent='Finding the best starting point in the catalog…';
  $('toolCount').textContent='0 results';
  $('activityList').replaceChildren();
  $('activityPanel').scrollTop=0;
  showAnswerSources([]);
  renderAnswer('The agent is gathering the relevant trial evidence. Follow its steps on the right.');
  $('answerPanel').scrollIntoView({behavior:'smooth',block:'start'});
  const pending=[];
  let resultCount=0;
  let finished=false;
  let streamedAnswer='';
  let answerFrame=0;
  const paintStreamedAnswer=()=>{
    answerFrame=0;
    renderAnswer(streamedAnswer);
    $('answerText').classList.add('streaming');
  };
  try {
    await readAgentStream(question, update => {
      if (update.type === 'status') {
        $('progressText').textContent=update.message;
      } else if (update.type === 'tool_call') {
        const card=element('div','activity-step');
        const head=element('div','activity-step-head');
        head.append(element('span','activity-number',String(pending.length+1).padStart(2,'0')),
                    element('strong','',toolLabel(update.tool)));
        const note=element('p','activity-decision',update.decision);
        const result=element('div','activity-result','Running tool…');
        const details=element('details','activity-raw');
        details.append(element('summary','','View inputs and full result'));
        const raw=element('pre','',`Inputs:\n${JSON.stringify(update.arguments,null,2)}`);
        details.append(raw);
        card.append(head,note,result,details);
        $('activityList').prepend(card);
        $('activityPanel').scrollTop=0;
        pending.push({id:update.id,tool:update.tool,card,result,raw,done:false});
        $('progressText').textContent=update.decision;
      } else if (update.type === 'tool_result') {
        const step=pending.find(item=>!item.done && item.id && item.id===update.id) ||
                   pending.find(item=>!item.done && item.tool===update.tool);
        resultCount+=1;
        $('toolCount').textContent=`${resultCount} result${resultCount===1?'':'s'}`;
        if (step) {
          step.done=true;
          step.result.textContent=update.summary;
          step.result.classList.add('ready');
          step.raw.textContent+=`\n\nResult:\n${formatToolOutput(update.content)}${update.truncated?'\n\n[Output truncated at 12,000 characters]':''}`;
          $('activityList').prepend(step.card);
          $('activityPanel').scrollTop=0;
        }
        $('progressText').textContent=update.summary;
      } else if (update.type === 'answer_token') {
        streamedAnswer+=update.text;
        $('progressText').textContent='Writing the evidence-backed answer…';
        if (!answerFrame) answerFrame=requestAnimationFrame(paintStreamedAnswer);
      } else if (update.type === 'answer_reset') {
        if (answerFrame) cancelAnimationFrame(answerFrame);
        answerFrame=0;
        streamedAnswer='';
        $('answerText').classList.remove('streaming');
        renderAnswer('Checking another piece of evidence…');
      } else if (update.type === 'final') {
        finished=true;
        if (answerFrame) cancelAnimationFrame(answerFrame);
        answerFrame=0;
        $('runStatus').textContent=update.status;
        $('agentLoading').classList.add('hidden');
        $('answerText').classList.remove('streaming');
        renderAnswer(update.answer);
        showAnswerSources(update.sources);
      }
    });
    if (!finished) throw new Error('The agent stream ended before a final answer arrived.');
  } catch(error) {
    if (answerFrame) cancelAnimationFrame(answerFrame);
    $('runStatus').textContent='error';
    $('agentLoading').classList.add('hidden');
    $('answerText').classList.remove('streaming');
    renderAnswer(error.message);
  } finally {
    button.disabled=false; button.firstChild.textContent='Ask the agent ';
  }
}

async function init() {
  const [health,facets,trials]=await Promise.all([json('/api/health'),json('/api/facets'),json('/api/trials')]);
  allTrials=trials.trials;
  $('catalogCount').textContent=`${health.trial_count} fictional trials`;
  $('statTrials').textContent=health.trial_count;
  $('statSources').textContent=allTrials.reduce((count,trial)=>count+trial.observations.length,0);
  $('statFlags').textContent=allTrials.filter(trial=>trial.status!=='consistent').length;
  const fields={crop:'crop',product:'product',country:'country',trialType:'trial_type'};
  for (const [id,key] of Object.entries(fields)) {
    for (const value of facets[key]) { const option=element('option','',value); option.value=value; $(id).append(option); }
  }
  renderTrials(allTrials);
  $('agentStatus').textContent=health.agent_configured?'Gemini agent connected · tool activity will be shown below':'Agent setup needed · set GOOGLE_API_KEY, then restart the app';
  if (!health.agent_configured) $('agentStatus').classList.add('unconfigured');
  $('askButton').disabled=!health.agent_configured;
  $('filterForm').addEventListener('change',loadTrials);
  $('trialId').addEventListener('input',loadTrials);
  $('resetFilters').onclick=()=>{$('filterForm').reset();loadTrials();};
  $('compareButton').onclick=compareSelected;
  $('previousPage').onclick=()=>changePage(-1);
  $('nextPage').onclick=()=>changePage(1);
  $('questionForm').addEventListener('submit',askQuestion);
  for (const chip of document.querySelectorAll('.prompt-chip')) chip.onclick=()=>{$('question').value=chip.textContent;$('question').focus();};
}

init().catch(error=>{$('catalogCount').textContent=`Unable to load catalog: ${error.message}`;});
