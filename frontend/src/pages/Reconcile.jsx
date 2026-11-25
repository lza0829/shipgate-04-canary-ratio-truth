import React, { useEffect, useState } from 'react'
import { api } from '../api'
import CanaryMeter from '../components/CanaryMeter'

export default function Reconcile() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(null)
  const load = () => api('/对账').then(setData).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  const repair = async (id) => {
    setErr('')
    setBusy(id)
    try {
      await api('/对账/金丝雀纠偏', {
        method: 'POST',
        body: JSON.stringify({ 发版单编号: id }),
      })
      await load()
    } catch (e) { setErr(e.message) } finally { setBusy(null) }
  }
  if (err) return <div className="panel err">{err}</div>
  if (!data) return <div className="panel">加载中</div>
  const s = data.发版统计 || {}
  const sum = data.金丝雀对账汇总 || {}
  return (
    <div className="panel">
      <h2>发布对账</h2>
      <div className="grid">
        {Object.entries(s).map(([k, v]) => (
          <div className="stat" key={k}><div className="n">{v}</div><div className="l">{k}</div></div>
        ))}
        <div className="stat"><div className="n">{data.晋升事件数}</div><div className="l">晋升事件数</div></div>
      </div>
      <h2>金丝雀比例对读（按选定真源重放）</h2>
      <p className="muted">
        真源：{data.比例真源}。回放比例按晋升事件附件重放，仅作对读；
        一致＝两套数吻合，待下次快照＝放行后合法改比例（有审计），脏比例＝无审计支撑的差额，可纠偏且只纠事件附件、真源不动。
      </p>
      <div className="grid">
        {Object.entries(sum).map(([k, v]) => (
          <div className={`stat reconcile-tag tag-${k}`} key={k}><div className="n">{v}</div><div className="l">{k}</div></div>
        ))}
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>发版单号</th><th>应用</th><th>状态</th><th>环境</th><th>真源比例（物化列）</th><th>回放比例（事件重放）</th><th>差额</th><th>结论</th><th>操作</th></tr>
          </thead>
          <tbody>
            {(data.金丝雀对账 || []).map((r) => (
              <tr key={r.编号} className={`row-${r.对账结论}`}>
                <td>{r.发版单号}</td><td>{r.应用}</td><td>{r.状态}</td><td>{r.当前环境 || '-'}</td>
                <td><CanaryMeter ratio={r.真源比例} hint={r.流量暗示} /></td>
                <td>{r.回放比例 === null || r.回放比例 === undefined ? '—' : `${r.回放比例}%`}</td>
                <td>{r.差额 === null || r.差额 === undefined ? '—' : (r.差额 > 0 ? `+${r.差额}` : r.差额)}</td>
                <td><span className={`conclusion con-${r.对账结论}`}>{r.对账结论}</span></td>
                <td>
                  {r.对账结论 === '脏比例' && (
                    <button
                      type="button" className="danger"
                      disabled={busy === r.编号}
                      onClick={() => repair(r.编号)}
                    >{busy === r.编号 ? '纠偏中…' : '纠偏事件附件'}</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>名册与实例</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>应用</th><th>环境</th><th>名册版本</th><th>实例版本们</th><th>红灯数</th></tr></thead>
          <tbody>
            {(data.名册与实例 || []).map((r, i) => (
              <tr key={i}><td>{r.应用}</td><td>{r.环境}</td><td>{r.名册版本}</td><td>{r.实例版本们 || '-'}</td><td>{r.红灯数}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row"><button type="button" className="secondary" onClick={load}>刷新</button></div>
    </div>
  )
}
