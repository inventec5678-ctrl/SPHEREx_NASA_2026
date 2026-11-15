// #/story: the research story that used to fill the lower two thirds of the home page, in the order of the paper:
//   00 PARALLAX · 01 Method · 02 Validation · 03 The search · 04 Your turn · 05 Paper.
// The home page keeps only the tool the challenge asks for; nothing here was cut, only moved.
import { Suspense, lazy, useEffect } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { L } from './lib.js'
import Parallax from './parallax.jsx'
import { ChapterRail, MethodHead, PaperCite, Search, ToolsHead, Validation, useManuscript } from './manuscript.jsx'
import { Near } from './near.jsx'
import { useReveal } from './reveal.js'

const Story = lazy(() => import('./story.jsx'))

function Fallback() {
  return <div className="route-loading" role="status" style={{ minHeight: '60svh' }}><i aria-hidden="true" /></div>
}

export default function StoryPage() {
  const lang = useLanguage()
  const ms = useManuscript()
  useEffect(() => { document.title = 'SPHEREx Sky Change · ' + L('它怎麼運作', 'How it works') }, [lang])
  useReveal()
  return (
    <div key={lang} className="home story-page">
      <Parallax lang={lang} asPage />
      <ChapterRail lang={lang} />
      <section id="ch-method" className="ms-band" aria-label={L('方法', 'Method')}><MethodHead v={ms} lang={lang} /></section>
      <Near><Suspense fallback={<Fallback />}><Story /></Suspense></Near>
      <Validation v={ms} lang={lang} />
      <Search v={ms} lang={lang} />
      <section id="ch-tools" aria-label={L('換你', 'Your turn')}>
        <ToolsHead lang={lang} />
      </section>
      <PaperCite lang={lang} />
    </div>
  )
}
