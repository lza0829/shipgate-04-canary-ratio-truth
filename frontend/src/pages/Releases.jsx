import React, { useEffect, useState } from 'react'
import { api } from '../api'

const FROZEN = ['已放行', '回滚中', '已回滚', '已关闭']

export default function Releases() {
  const [rows, setRows] = useState([])
  const [apps, setApps] = useState([])
  const [appId, setAppId] = useState('')
  const [ver, setVer] = useState('')
  const [digest, setDigest] = useState('')
  const [err, setErr] = useState('')
  const [ratioDraft, setRatioDraft] = useState({})
  const load = async () => {
    setRows(await api('/发版单'))
    const a = await api('/应用')
    setApps(a)
    if (!appId && a[0]) setAppId(String(a[0].编号))
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])
  const create = async () => {
    setErr('')
    try {
      await api('/发版单', {
        method: 'POST',
        body: JSON.stringify({ 应用编号: Number(appId), 目标版本: ver, 制品摘要: digest }),
      })
      setVer(''); setDigest(''); load()
    } catch (e) { setErr(e.message) }
  }
  const pipeline = async (id, status) => {
    setErr('')
    try {
      await api(`/发版单/${id}/流水线`, { method: 'POST', body: JSON.stringify({ 流水线: status }) })
      load()
    } catch (e) { setErr(e.message) }
  }
  const admit = async (id) => {
    setErr('')
    try {
      await api(`/发版单/${id}/入闸`, { method: 'POST', body: '{}' })
      load()
    } catch (e) { setErr(e.message) }
  }
  const saveRatio = async (id) => {
    setErr('')
    const value = Number(ratioDraft[id])
    if (!Number.isInteger(value) || value < 0 || value > 100) {
      setErr('金丝雀比例须为 0 到 100 的整数')
      return
    }
    try {
      // 唯一写口：后端同事务更新物化真源字段并落审计
      await api(`/发版单/${id}/金丝雀比例`, {
        method: 'POST',
        body: JSON.stringify({ 金丝雀比例: value }),
      })
      setRatioDraft((d) => { const n = { ...d }; delete n[id]; return n })
      load()
    } catch (e) { setErr(e.message) }
  }
  return (
    <div className="panel">
      <h2>发版单</h2>
      {err && <p className="err">{err}</p>}
      <div className="row">
        <label>应用
          <select value={appId} onChange={(e) => setAppId(e.target.value)}>
            {apps.map((a) => <option key={a.编号} value={a.编号}>{a.名称}</option>)}
          </select>
        </label>
        <label>目标版本<input value={ver} onChange={(e) => setVer(e.target.value)} placeholder="1.4.0" /></label>
        <label>制品摘要<input value={digest} onChange={(e) => setDigest(e.target.value)} placeholder="sha256:..." /></label>
        <button type="button" onClick={create}>申请入闸</button>
        <button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新</button>
      </div>
      <p className="muted">比例真源：发版单「金丝雀比例」物化列；放行事件只快照当时值作附件，总览/对账/实例均按此列解读。</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>发版单号</th><th>应用</th><th>目标版本</th><th>状态</th><th>流水线</th><th>当前环境</th><th>金丝雀比例（真源）</th><th>操作</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const frozen = FROZEN.includes(r.状态)
              const editing = r.编号 in ratioDraft
              return (
                <tr key={r.编号}>
                  <td>{r.发版单号}</td><td>{r.应用}</td><td>{r.目标版本}</td>
                  <td>{r.状态}</td><td>{r.流水线}</td><td>{r.当前环境 || '-'}</td>
                  <td>
                    {frozen ? (
                      <span title="落定后比例冻结，事件回放不得回改">
                        <strong>{r.金丝雀比例}%</strong>
                        <span className="muted">（已冻结）</span>
                      </span>
                    ) : editing ? (
                      <span className="ratio-edit">
                        <input
                          type="number" min="0" max="100"
                          value={ratioDraft[r.编号]}
                          onChange={(e) => setRatioDraft((d) => ({ ...d, [r.编号]: e.target.value }))}
                          aria-label={`${r.发版单号}金丝雀比例`}
                        />
                        <button type="button" onClick={() => saveRatio(r.编号)}>存比例</button>
                        <button
                          type="button" className="secondary"
                          onClick={() => setRatioDraft((d) => { const n = { ...d }; delete n[r.编号]; return n })}
                        >取消</button>
                      </span>
                    ) : (
                      <button
                        type="button" className="secondary ratio-btn"
                        title="修改比例走唯一写口，后端同事务落审计"
                        onClick={() => setRatioDraft((d) => ({ ...d, [r.编号]: String(r.金丝雀比例) }))}
                      >{r.金丝雀比例}% ✎</button>
                    )}
                  </td>
                  <td>
                    <button type="button" className="secondary" onClick={() => pipeline(r.编号, '绿')}>流水线绿</button>{' '}
                    <button type="button" className="danger" onClick={() => pipeline(r.编号, '红')}>流水线红</button>{' '}
                    <button type="button" onClick={() => admit(r.编号)}>入闸</button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
