import React from 'react'

// 金丝雀比例条（单序列 meter）：只解读真源字段 releases.canary_ratio，
// 不做任何重算。三态语义由颜色+文字共同承载，不靠颜色单独表意。
//   100%  -> 全量（绿）
//   1..99 -> 金丝雀 N%（琥珀）
//   0%    -> 零流量（钢灰）
export default function CanaryMeter({ ratio, hint }) {
  const v = Number(ratio) || 0
  const clamped = Math.max(0, Math.min(100, v))
  const state = v >= 100 ? 'full' : v <= 0 ? 'zero' : 'canary'
  const label = v >= 100 ? '全量' : v <= 0 ? '零流量' : `金丝雀 ${v}%`
  return (
    <span className={`canary-meter canary-${state}`} title={hint || label}>
      <span className="canary-track" aria-hidden="true">
        <span className="canary-fill" style={{ width: `${clamped}%` }} />
      </span>
      <span className="canary-label">{v}% · {label}</span>
    </span>
  )
}
