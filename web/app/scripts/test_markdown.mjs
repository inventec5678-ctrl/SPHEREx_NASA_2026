// The assistant's light Markdown: node scripts/test_markdown.mjs   (also: npm test)
import { parseBlocks, parseInline } from '../src/ask/markdown.js'
let bad = 0
const eq = (name, got, want) => { if (JSON.stringify(got) !== JSON.stringify(want)) { bad++; console.log('FAIL', name, JSON.stringify(got), '!=', JSON.stringify(want)) } }
eq('paragraphs', parseBlocks('a\nb\n\nc'), [{ type: 'p', lines: ['a', 'b'] }, { type: 'p', lines: ['c'] }])
eq('bullets', parseBlocks('Intro:\n- one\n* two\n• three'), [{ type: 'p', lines: ['Intro:'] }, { type: 'ul', items: ['one', 'two', 'three'] }])
eq('numbered', parseBlocks('2. x\n3) y'), [{ type: 'ol', start: 2, items: ['x', 'y'] }])
eq('continuation', parseBlocks('- one\n  more'), [{ type: 'ul', items: ['one more'] }])
eq('heading', parseBlocks('### Why ###\ntext'), [{ type: 'h', text: 'Why' }, { type: 'p', lines: ['text'] }])
eq('bold line is not a bullet', parseBlocks('**Note**: x'), [{ type: 'p', lines: ['**Note**: x'] }])
eq('zh list', parseBlocks('- **溫度較低**：輻射集中在紅外線 [1]')[0].type, 'ul')
eq('inline', parseInline('**Hot** dust `D6` [1, 3] and *x*'), [{ t: 'b', v: 'Hot' }, { t: 'text', v: ' dust ' }, { t: 'code', v: 'D6' }, { t: 'text', v: ' ' }, { t: 'cite', n: [1, 3] }, { t: 'text', v: ' and *x*' }])
eq('half-streamed bold stays text', parseInline('**Hot'), [{ t: 'text', v: '**Hot' }])
eq('html is text', parseInline('<b>x</b>'), [{ t: 'text', v: '<b>x</b>' }])
eq('empty', parseBlocks(''), [])
console.log(bad ? `${bad} failed` : 'all markdown cases pass'); process.exit(bad ? 1 : 0)
