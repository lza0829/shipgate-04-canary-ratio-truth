import React, { useEffect, useState } from 'react'
import { api } from '../api'
import CanaryMeter from '../components/CanaryMeter'

export default function Health() {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const load = () => api('/实例').then(setRows).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  const setH = async (id, health) => {
    setErr('')
    try {
      await api(`/实例/${id}/健康`, { method: 'POST', body: JSON.stringify({ 健康: health }) })
      load()
    } catch (e) { setErr(e.message) }
  }
  return (
    <div className="panel">
      <h2>健康探针</h2>
      {err && <p className="err">{err}</p>}
      <p className="muted">流量暗示只解读发版单真源比例列，探针与切流同命运（探针状态独立操作，不在本页重算比例）。</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>应用</th><th>环境</th><th>版本</th><th>健康</th><th>发版单</th><th>金丝雀比例</th><th>流量暗示</th><th>操作</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.编号}>
                <td>{r.应用}</td><td>{r.环境}</td><td>{r.版本}</td><td>{r.健康}</td><td>{r.发版单编号 || '-'}</td>
                <td>{r.金丝雀比例 === null || r.金丝雀比例 === undefined ? '—' : <CanaryMeter ratio={r.金丝雀比例} hint={r.流量暗示} />}</td>
                <td>{r.流量暗示}</td>
                <td>
                  <button type="button" onClick={() => setH(r.编号, '探针绿')}>探针绿</button>{' '}
                  <button type="button" className="danger" onClick={() => setH(r.编号, '探针红')}>探针红</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row"><button type="button" className="secondary" onClick={load}>刷新</button></div>
    </div>
  )
}
