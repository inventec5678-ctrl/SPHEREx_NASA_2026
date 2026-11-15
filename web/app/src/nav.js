// Hash navigation: #/  ·  #/field/<id>  ·  #/field/<id>/track/<n>
export function go(field, track) {
  location.hash = field == null ? '#/' : track == null ? `#/field/${encodeURIComponent(field)}` : `#/field/${encodeURIComponent(field)}/track/${track}`
}
// #/universe/<field>[/<body key>]: the body-reconstruction page (spectrum -> predicted appearance -> rebuild)
export function goUniverse(field = 'cybele', key) {
  location.hash = `#/universe/${encodeURIComponent(field)}${key ? '/' + encodeURIComponent(key) : ''}`
}
