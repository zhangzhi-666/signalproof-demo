'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const state = { examples: [], validations: new Map(), activeCase: 'ft-shift', revealed: false, tests: [] };
const labels = { correct: '正确', wrong: '错误', incomplete: '不完整', unknown: '无法判断' };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function math(node, latex, fallback = latex) {
  if (window.katex && latex) {
    try { window.katex.render(latex, node, { throwOnError: false, trust: false, strict: false, output: 'htmlAndMathml' }); return; }
    catch (_) { /* Preserve the original expression when math rendering is unavailable. */ }
  }
  node.textContent = fallback || '';
}
function renderStaticMath() {
  $$('[data-math]').forEach(node => math(node, node.dataset.math));
}
async function getJSON(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}
function errorNote(message) { return element('p', 'error-note', message); }
function caseHref(id) { return `lab.html?case=${encodeURIComponent(id)}#verify`; }

function setCase(id, reveal = false) {
  const sample = state.examples.find(item => item.id === id);
  if (!sample) return;
  state.activeCase = id;
  state.revealed = reveal;
  const activeTab = $(`[data-case="${id}"]`);
  $$('.demo-tabs [role="tab"]').forEach(tab => {
    const active = tab === activeTab;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  if (activeTab) $('#demo-panel').setAttribute('aria-labelledby', activeTab.id);
  const content = $('#demo-content');
  content.replaceChildren(element('h3', '', sample.title), element('p', '', sample.task));
  $('#demo-hint').textContent = `想一想 · ${sample.hint}`;
  $('#demo-lab-link').href = caseHref(sample.id);
  $('#demo-step-count').textContent = `${sample.steps.length} 行`;
  const list = $('#demo-steps');
  list.replaceChildren();
  const saved = state.validations.get(id);
  const transitions = saved?.result?.steps || [];
  const firstError = saved?.result?.firstError ?? sample.expectedFirstError;
  sample.steps.forEach((expression, index) => {
    const line = index + 1;
    const row = element('li');
    const number = element('span', 'step-number', String(line).padStart(2, '0'));
    const formula = element('div', 'step-formula');
    const latex = index === 0 ? transitions[0]?.beforeLatex : transitions.find(step => step.line === line)?.afterLatex;
    if (latex) math(formula, latex, expression);
    else formula.append(element('code', '', expression));
    const annotation = element('span', 'step-state');
    if (reveal && firstError === line) {
      row.classList.add('is-first-error');
      annotation.textContent = '首错';
    } else if (reveal && firstError && line > firstError) {
      row.classList.add('is-inherited');
      annotation.textContent = '受前错影响';
    } else if (reveal && line > 1) {
      const transition = transitions.find(step => step.line === line);
      annotation.textContent = labels[transition?.localStatus || sample.expected] || '';
    }
    row.append(number, formula, annotation);
    list.append(row);
  });
  const button = $('#reveal-button');
  button.setAttribute('aria-expanded', String(reveal));
  button.textContent = reveal ? '收起分析 ↑' : '揭晓分析 ↓';
  const analysis = $('#demo-analysis');
  analysis.hidden = !reveal;
  analysis.replaceChildren();
  if (reveal) {
    const status = saved?.actual || sample.expected;
    const heading = status === 'wrong' ? `首个错误出现在第 ${firstError} 行` : status === 'incomplete' ? '表达式成立，但答案还不完整' : status === 'unknown' ? '当前条件下，保留“无法判断”' : '各步符合预期的等价关系';
    analysis.append(element('strong', '', heading), element('p', '', sample.takeaway));
    const target = transitions.find(step => step.line === firstError) || transitions.find(step => step.status === 'incomplete');
    if (target?.expectedLatex) {
      const correction = element('div', 'analysis-formula');
      correction.style.cssText = 'overflow-x:auto;padding:12px 0 3px';
      math(correction, target.expectedLatex, target.expected);
      analysis.append(correction);
    }
    if (target?.ruleIds?.length) {
      analysis.append(element('p', 'analysis-note', `对应规则：${target.ruleIds.join('、')} · ${(target.ruleNames || []).join('、')}`));
    }
    analysis.append(element('p', 'analysis-note', saved ? '分析来自已保存的案例核验结果。修改条件或推导后，请进入实验室重新计算。' : '此处为案例预设讲解；核验报告未加载，实时结果请进入实验室计算。'));
  }
}

function setupTabs() {
  const tabs = $$('.demo-tabs [role="tab"]');
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => setCase(tab.dataset.case));
    tab.addEventListener('keydown', event => {
      let next = index;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else return;
      event.preventDefault();
      setCase(tabs[next].dataset.case);
      tabs[next].focus();
    });
  });
  $('#reveal-button').addEventListener('click', () => setCase(state.activeCase, !state.revealed));
}

const artBase = '<path d="M20 116H300M55 18V132" stroke="currentColor" opacity=".15" fill="none"/><path d="M20 44H300M20 80H300M110 18V132M165 18V132M220 18V132M275 18V132" stroke="currentColor" opacity=".045" fill="none"/>';
function caseArtwork(id) {
  const drawings = {
    'ft-shift': '<path d="M24 116C58 116 57 111 72 88S86 34 100 34S114 67 129 92S150 116 179 116" fill="none" stroke="#a2b6a9" stroke-width="2" stroke-dasharray="4 4"/><path d="M114 116C148 116 147 111 162 88S176 34 190 34S204 67 219 92S240 116 279 116" fill="none" stroke="#408c6d" stroke-width="2.8"/><path d="M111 29H175L168 24M175 29L168 34" stroke="#408c6d" fill="none"/><text x="227" y="55" fill="#6a947e" font-size="11">−jωa</text>',
    'conv': '<path d="M48 116L74 50L100 116" stroke="#859aaf" stroke-width="2" fill="none"/><path d="M158 116V37M153 44L158 37L163 44" stroke="#8198a8" stroke-width="2" fill="none"/><path d="M213 116L239 50L265 116" stroke="#527e94" stroke-width="3" fill="none"/><text x="117" y="81" fill="#94a5b2" font-size="18">∗</text><text x="185" y="81" fill="#94a5b2" font-size="17">=</text>',
    'lt-initial': '<path d="M55 38C94 79 148 109 276 116L276 117H55Z" fill="#b6a27c" opacity=".09"/><path d="M55 38C94 79 148 109 276 116" stroke="#a38c62" stroke-width="2.8" fill="none"/><circle cx="55" cy="38" r="4" fill="#ad926a"/><path d="M65 38H107" stroke="#b2a28b" stroke-dasharray="3 4"/><text x="116" y="41" fill="#9d8b70" font-size="11">x(0⁻) = 2</text><text x="175" y="80" fill="#aa9b85" font-size="13">sX(s) − x(0⁻)</text>',
    'ft-scale': '<path d="M41 116L84 39L127 116" fill="none" stroke="#92b2bc" stroke-width="2"/><path d="M156 116L185 39L214 116" fill="none" stroke="#4b8e9d" stroke-width="2.7"/><path d="M218 43H278" stroke="#9abec2" stroke-width="1.3"/><text x="233" y="65" fill="#548b96" font-size="12">1 / |a|</text><path d="M135 90H149M143 85L149 90L143 95" stroke="#7baab4" fill="none"/>',
    'z-roc': '<path d="M50 14H271V139H50Z M157 76m-34 0a34 34 0 1 0 68 0a34 34 0 1 0-68 0" fill="#769582" fill-rule="evenodd" opacity=".1"/><path d="M71 76H250M157 12V140" stroke="#8da794" stroke-width="1"/><circle cx="157" cy="76" r="34" fill="none" stroke="#6c9278" stroke-width="1.8" stroke-dasharray="4 4"/><path d="M186 72L194 80M186 80L194 72" stroke="#6c9278" stroke-width="1.5"/><text x="215" y="39" fill="#728e79" font-size="11">|z| &gt; ½</text>',
    'unknown': '<path d="M31 78C45 33 54 32 64 76S79 123 90 77S110 31 118 76S132 121 140 77S152 34 159 77S169 117 175 77S184 40 189 77S198 114 203 77S211 42 216 77S224 111 229 77S237 45 242 77S250 109 255 77S263 45 268 77" stroke="#92809e" stroke-width="2" fill="none"/><text x="248" y="37" fill="#a498ad" font-size="24">?</text>'
  };
  return `<svg viewBox="0 0 320 150" aria-hidden="true" style="color:#658472">${artBase}${drawings[id] || drawings['ft-shift']}</svg>`;
}
function renderGallery() {
  const ids = ['ft-shift', 'conv', 'lt-initial', 'ft-scale', 'z-roc', 'unknown'];
  const gallery = $('#case-gallery');
  gallery.replaceChildren();
  ids.forEach((id, index) => {
    const sample = state.examples.find(item => item.id === id);
    if (!sample) return;
    const card = element('a', 'case-card');
    card.href = caseHref(id);
    const art = element('div', 'case-art');
    art.innerHTML = caseArtwork(id);
    art.append(element('span', 'art-index', `${String(index + 1).padStart(2, '0')} / ILLUSTRATION`));
    const body = element('div', 'case-card-content');
    const meta = element('div', 'case-meta');
    meta.append(element('span', '', sample.category), element('span', '', `${sample.difficulty} · ${sample.kind}`));
    const footer = element('div', 'case-card-footer');
    footer.append(element('span', '', sample.concept), element('span', '', '↗'));
    body.append(meta, element('h3', '', sample.title), element('p', '', sample.pitfall), footer);
    card.append(art, body);
    gallery.append(card);
  });
  $('#gallery-count').textContent = String(state.examples.length);
  const count = $('#hero-case-count');
  count.replaceChildren(document.createTextNode(String(state.examples.length)), element('span', '', '例'));
}

function selectTest(index, focus = false) {
  const test = state.tests[index];
  if (!test) return;
  $$('.test-tile').forEach((tile, tileIndex) => {
    tile.tabIndex = tileIndex === index ? 0 : -1;
    tile.setAttribute('aria-pressed', String(tileIndex === index));
    if (focus && tileIndex === index) tile.focus();
  });
  const preview = $('#test-preview');
  const status = `预期：${labels[test.expected] || test.expected} / 首错 ${test.expectedFirstError ?? '无'}　实际：${labels[test.actual] || test.actual} / 首错 ${test.actualFirstError ?? '无'}`;
  preview.replaceChildren(
    element('strong', '', `${test.passed ? '✓' : '×'} ${test.id} · ${test.title}`),
    element('span', 'preview-state', status),
    element('code', '', (test.steps || []).map((line, idx) => `${idx + 1}. ${line}`).join('\n'))
  );
}
function renderTests(report) {
  if (!Array.isArray(report.results) || !report.results.length) throw new Error('固定验收报告缺少 results');
  state.tests = report.results;
  const passed = state.tests.filter(test => test.passed === true).length;
  const total = state.tests.length;
  const correct = state.tests.filter(test => test.expected === 'correct').length;
  const wrong = state.tests.filter(test => test.expected === 'wrong').length;
  $('#test-ratio').textContent = `${passed} / ${total}`;
  $('#correct-count').textContent = String(correct);
  $('#wrong-count').textContent = String(wrong);
  $('#hero-test-count').replaceChildren(document.createTextNode(String(total)), element('span', '', '条'));
  const grid = $('#test-tiles');
  grid.replaceChildren();
  grid.setAttribute('aria-label', `固定验收集 ${total} 条，${passed} 条符合预期。使用方向键选择测试，按 Tab 离开。`);
  state.tests.forEach((test, index) => {
    const tile = element('button', `test-tile ${test.expected === 'correct' ? 'correct' : 'wrong'} ${test.passed ? 'passed' : 'failed'}`);
    const description = `${test.id}，${test.title}，${test.passed ? '符合预期' : '结果偏差'}`;
    tile.type = 'button';
    tile.title = description;
    tile.setAttribute('aria-label', description);
    tile.tabIndex = index === 0 ? 0 : -1;
    tile.addEventListener('click', () => selectTest(index));
    tile.addEventListener('keydown', event => {
      const columns = getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length;
      let next = index;
      if (event.key === 'ArrowRight') next = Math.min(total - 1, index + 1);
      else if (event.key === 'ArrowLeft') next = Math.max(0, index - 1);
      else if (event.key === 'ArrowDown') next = Math.min(total - 1, index + columns);
      else if (event.key === 'ArrowUp') next = Math.max(0, index - columns);
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = total - 1;
      else return;
      event.preventDefault();
      selectTest(next, true);
    });
    grid.append(tile);
  });
  selectTest(0);
}
function renderValidation(report) {
  if (!Array.isArray(report.cases) || !report.cases.length) throw new Error('教学核验报告缺少 cases');
  state.validations = new Map(report.cases.map(item => [item.id, item]));
  const passed = report.cases.filter(item => item.passed === true).length;
  $('#examples-ratio').textContent = `${passed} / ${report.cases.length}`;
  const date = report.generatedAt ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(report.generatedAt)) : '';
  $('#examples-summary').textContent = `${report.cases.length} 个情境案例逐一核对状态与首错位置，包含正确、错误、条件不足及收敛域缺失。${date ? `报告日期：${date}。` : ''}`;
  const breakdown = $('#examples-breakdown');
  breakdown.replaceChildren();
  ['correct', 'wrong', 'unknown', 'incomplete'].forEach(status => {
    const count = report.cases.filter(item => item.expected === status).length;
    breakdown.append(element('span', '', `${labels[status]} ${count}`));
  });
  if (state.examples.length) setCase(state.activeCase, state.revealed);
}

async function initialize() {
  renderStaticMath();
  setupTabs();
  $('#reveal-button').disabled = true;
  const jobs = [
    getJSON('data/examples.json').then(examples => {
      if (!Array.isArray(examples) || !examples.length) throw new Error('案例数据为空');
      state.examples = examples;
      renderGallery();
      setCase('ft-shift');
      $('#reveal-button').disabled = false;
    }).catch(() => {
      $('#demo-content').replaceChildren(errorNote('案例暂时未能载入。请刷新页面，或直接进入实验室。'));
      $('#case-gallery').replaceChildren(errorNote('教学案例数据加载失败；仍可通过“探索全部案例”进入实验室。'));
    }),
    getJSON('docs/test-results.json').then(renderTests).catch(() => {
      $('#test-preview').replaceChildren(errorNote('固定验收报告未能载入，当前不显示通过统计。可打开原始报告检查或进入实验室重新运行。'));
      $('#test-ratio').textContent = '未加载';
    }),
    getJSON('docs/examples-validation.json').then(renderValidation).catch(() => {
      $('#examples-ratio').textContent = '未加载';
      $('#examples-summary').textContent = '教学案例核验报告未能载入。此处不推断通过情况，请打开原始报告检查。';
    })
  ];
  await Promise.allSettled(jobs);
}
initialize();
