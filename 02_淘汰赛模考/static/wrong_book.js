(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const date = seconds => new Date(seconds * 1000).toLocaleString('zh-CN');
  let page = 1, requestNumber = 0;
  async function load() {
    const request = ++requestNumber;
    const response = await fetch(`/api/drill/wrongs?status=${encodeURIComponent($('wrong-filter').value)}&page=${page}`);
    if (response.status === 401) { location.href = '/login'; return; }
    const data = await response.json();
    if (request !== requestNumber) return;
    if (!response.ok) throw Error(data.error || '无法读取错题本');
    $('wrong-error').classList.add('hidden');
    $('wrong-stats').textContent = `错题历史 ${data.stats.total} 道 · 待复习 ${data.stats.active} 道 · 已掌握 ${data.stats.mastered} 道`;
    $('wrong-list').innerHTML = data.items.length ? data.items.map(item => `<details class="card wrong-item"><summary><span class="mastery-tag ${item.mastered_at?'mastered':''}">${item.mastered_at?'已掌握':'待复习'}</span><strong>${esc(item.stem)}</strong><span class="muted">累计答错 ${item.wrong_count} 次</span></summary><div class="wrong-detail"><p class="muted">${item.type==='multi'?'多选题':item.type==='judge'?'判断题':'单选题'}${item.module?' · '+esc(item.module):''}</p>${item.options.map(option=>`<div class="option ${item.correct.includes(option.key)?'correct-choice':''}"><strong>${esc(option.key)}</strong><span>${esc(option.text)}</span></div>`).join('')}<div class="review ${item.mastered_at?'':'bad'}"><p>上次错答：${esc(item.last_wrong_answer.join('、'))}</p><p>正确答案：${esc(item.correct.join('、'))}</p><p class="drill-explanation">解析：${esc(item.explanation || '题库暂未提供解析。')}</p></div><p class="muted">首次答错：${esc(date(item.first_wrong_at))} · 最近答错：${esc(date(item.last_wrong_at))}${item.mastered_at?' · 已掌握：'+esc(date(item.mastered_at)):''}</p><p class="muted">来源：${esc(item.source || '未标注')}</p></div></details>`).join('') : '<section class="card"><h2>当前筛选下暂无错题</h2><p class="muted">刷题答错会自动加入错题本；答对后的记录可在“已掌握”或“全部历史”中查看。</p><a class="button" href="/drill">前往全题库刷题</a></section>';
    const pages = Math.max(1, Math.ceil(data.total / data.per_page));
    $('wrong-page').textContent = `第 ${page} / ${pages} 页 · ${data.total} 道`;
    $('wrong-prev').disabled = page <= 1; $('wrong-next').disabled = page >= pages;
  }
  function refresh() { load().catch(error => { $('wrong-error').textContent = error.message; $('wrong-error').classList.remove('hidden'); }); }
  $('wrong-filter').addEventListener('change', () => { page=1; refresh(); });
  $('wrong-prev').addEventListener('click', () => { if (page>1) { page--; refresh(); } });
  $('wrong-next').addEventListener('click', () => { page++; refresh(); });
  refresh();
})();
