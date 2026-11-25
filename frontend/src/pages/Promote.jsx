import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Promote() {
  const [rows, setRows] = useState([])
  const [rid, setRid] = useState('')
  const [env, setEnv] = useState('预')
  const [err, setErr] = useState('')
  const load = async () => {
    const all = await api('/发版单')
    const active = all.filter((r) => ['已入闸', '晋升中'].includes(r.状态))
    setRows(active)
    if (!rid && active[0]) setRid(String(active[0].编号))
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])
  const go = async () => {
    setErr('')
    try {
      // 放行当下：后端把真源比例快照进晋升事件，与状态推进同一写事务
      await api(`/发版单/${rid}/晋升`, { method: 'POST', body: JSON.stringify({ 目标环境: env }) })
      load()
    } catch (e) { setErr(e.message) }
  }
  const picked = rows.find((r) => String(r.编号) === String(rid))
  return (
    <div className="panel">
      <h2>环境晋升</h2>
      {err && <p className="err">{err}</p>}
      <div className="row">
        <label>发版单
          <select value={rid} onChange={(e) => setRid(e.target.value)}>
            {rows.map((r) => <option key={r.编号} value={r.编号}>{r.发版单号} · {r.应用} · {r.当前环境}</option>)}
          </select>
        </label>
        <label>目标环境
          <select value={env} onChange={(e) => setEnv(e.target.value)}>
            <option value="测">测</option>
            <option value="预">预</option>
            <option value="产">产</option>
          </select>
        </label>
        <button type="button" onClick={go}>晋升</button>
        <button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新</button>
      </div>
      {picked && (
        <p className="muted">
          本次放行将把发版单当前真源比例 <strong>{picked.金丝雀比例}%</strong> 快照写入晋升事件附件；
          要改比例请先到「发版单」页（唯一写口），放行后比例冻结。
        </p>
      )}
      <div className="table-wrap">
        <table>
          <thead><tr><th>发版单号</th><th>应用</th><th>目标版本</th><th>状态</th><th>当前环境</th><th>金丝雀比例（放行快照值）</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.编号}><td>{r.发版单号}</td><td>{r.应用}</td><td>{r.目标版本}</td><td>{r.状态}</td><td>{r.当前环境}</td><td>{r.金丝雀比例}%</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
