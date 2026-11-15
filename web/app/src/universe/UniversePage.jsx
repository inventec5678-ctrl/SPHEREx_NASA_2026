import { L } from '@sx/i18n/core.js'
// Body reconstruction: every detected source is a sphere built from parameters predicted from its own
// SPHEREx spectrum (stars, galaxies) or from JPL data and reflectance (asteroids). Pick one, see the
// spectrum and the fit, choose a preset or move the sliders, rebuild.
import { useEffect, useState } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { api } from '../lib.js'
import Universe from './Universe.jsx'

export default function UniversePage({ fieldId, pick }) {
  useLanguage()
  const [fields, setFields] = useState([])
  useEffect(() => { api('/api/fields').then(setFields).catch(() => {}) }, [])
  useEffect(() => { document.title = 'SPHEREx Sky Change · ' + (L('星體重建', 'Body reconstruction')) }, [])
  return (
    <div className="upage">
      <header className="upage-head">
        <h1>星體重建</h1>
        <p>每一顆球都是一個 SPHEREx 偵測到的天體。點它：看它在 102 個波段量到的光譜，模型從光譜判定它是什麼（恆星的溫度、星系、小行星的顏色），再依這組參數把它建出來。也可以換一個預設、拖滑桿重建。</p>
      </header>
      {fields.some((f) => f.has_universe) && <Universe fields={fields} page initialField={fieldId} pick={pick} />}
    </div>
  )
}
