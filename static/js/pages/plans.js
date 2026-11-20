import { api } from '../api.js';

function detailHtml(r) {
  const rows = (r.items || []).map(f => `<tr>
    <td>${f.path}</td>
    <td>${f.size_bytes}</td>
    <td><span class="tag">${f.status}</span></td>
    <td>${f.status === '已入计划'
      ? `<button data-detach="${r.plan.id}:${f.id}" type="button">拆项退挂</button>` : ''}</td>
  </tr>`).join('');
  const vouchers = (r.detaches || []).map(d => `<tr>
    <td>${d.path}</td>
    <td>${d.size_bytes}</td>
    <td><span class="tag">已退挂</span></td>
    <td class="muted">#${d.id} · ${d.operator || '—'} · ${d.created_at}</td>
  </tr>`).join('');
  return `
    <table class="grid">
      <thead><tr><th>挂载项</th><th>字节</th><th>状态</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="4" class="muted">暂无挂载项</td></tr>'}</tbody>
    </table>
    ${vouchers ? `<h4>退挂凭证</h4>
    <table class="grid">
      <thead><tr><th>碎件</th><th>字节</th><th>状态</th><th>凭证</th></tr></thead>
      <tbody>${vouchers}</tbody>
    </table>` : ''}`;
}

async function loadDetail(pid, view, setMsg) {
  const r = await api('/api/plans/' + pid);
  const box = document.getElementById('d' + pid);
  if (!box) return;
  box.innerHTML = detailHtml(r);
  box.querySelectorAll('[data-detach]').forEach(btn => {
    btn.onclick = async () => {
      const [planId, fileId] = btn.dataset.detach.split(':');
      try {
        const d = await api('/api/plans/' + planId + '/detach', {
          method: 'POST',
          body: JSON.stringify({ file_id: Number(fileId) }),
        });
        setMsg('已退挂 1 项，计划余 ' + d.plan_bytes + ' 字节');
        await renderPlans(view, setMsg);
        await loadDetail(planId, view, setMsg);
      } catch (e) { setMsg(e.message, true); }
    };
  });
}

export async function renderPlans(view, setMsg) {
  const j = await api('/api/plans');
  view.innerHTML = `
    <section class="card">
      <h2>压实计划</h2>
      <div class="row">
        <label>编号<input id="code" value="CP-NEW-1" /></label>
        <label>标题<input id="title" value="新压实计划" /></label>
        <label>目标表<input id="table" value="dw_payments" /></label>
        <button class="primary" id="create" type="button">创建计划</button>
      </div>
    </section>
    <section class="wall" style="margin-top:1rem">
      ${(j.items || []).map(p => `<article class="card">
        <h3>${p.plan_code}</h3>
        <span class="tag">${p.status}</span>
        <p>${p.title}</p>
        <p class="muted">${p.target_table} · ${p.item_count} 文件 · ${p.plan_bytes} 字节</p>
        <div class="row">
          <button data-attach="${p.id}" type="button">挂入碎文件</button>
          <button data-pub="${p.id}" class="primary" type="button">发布</button>
          <button data-detail="${p.id}" type="button">详情</button>
        </div>
        <div class="detail" id="d${p.id}"></div>
      </article>`).join('') || '<p class="muted">暂无计划</p>'}
    </section>`;
  document.getElementById('create').onclick = async () => {
    try {
      await api('/api/plans', { method:'POST', body: JSON.stringify({
        plan_code: document.getElementById('code').value,
        title: document.getElementById('title').value,
        target_table: document.getElementById('table').value,
      })});
      setMsg('计划已创建');
      await renderPlans(view, setMsg);
    } catch (e) { setMsg(e.message, true); }
  };
  view.querySelectorAll('[data-attach]').forEach(btn => {
    btn.onclick = async () => {
      try {
        const r = await api('/api/plans/' + btn.dataset.attach + '/attach', { method:'POST', body:'{}' });
        setMsg('挂入 ' + r.attached + ' 个碎文件');
        await renderPlans(view, setMsg);
      } catch (e) { setMsg(e.message, true); }
    };
  });
  view.querySelectorAll('[data-pub]').forEach(btn => {
    btn.onclick = async () => {
      try {
        await api('/api/plans/' + btn.dataset.pub + '/publish', { method:'POST', body:'{}' });
        setMsg('已发布');
        await renderPlans(view, setMsg);
      } catch (e) { setMsg(e.message, true); }
    };
  });
  view.querySelectorAll('[data-detail]').forEach(btn => {
    btn.onclick = async () => {
      try {
        await loadDetail(btn.dataset.detail, view, setMsg);
      } catch (e) { setMsg(e.message, true); }
    };
  });
}
