// Visual effects tuned to the site's palette, built on React Bits components (./rb, MIT + Commons Clause).
// All of them respect prefers-reduced-motion (the underlying components check it) and pause off-screen.
import Galaxy from './rb/Galaxy.jsx'
import GlareHover from './rb/GlareHover.jsx'
import GradientText from './rb/GradientText.jsx'
import ShinyText from './rb/ShinyText.jsx'
import SpotlightCard from './rb/SpotlightCard.jsx'
import StarBorder from './rb/StarBorder.jsx'
import { gpuOK } from './canvas.js'

const SUNLIT = '#f2e6c9'          // SELENE accent: sunlit cream, with earth blue for focus
const EARTH = '#6fb6ff'
const SURFACE = '#0b0f18'

// A slow, faint star field fixed behind a content page (one WebGL canvas, under everything).
export function SkyBackdrop() {
  // without GPU acceleration: a still star field in CSS (the shader would hold the page for seconds)
  if (!gpuOK()) return <div className="sky-backdrop still" aria-hidden="true" />
  return (
    <div className="sky-backdrop" aria-hidden="true">
      <Galaxy starColors={['#ffffff', '#ffe2b0', '#a9d4ff']} density={0.9} starSpeed={0.2} speed={0.5} rotationSpeed={0.02}
        glowIntensity={0.22} twinkleIntensity={0.45} saturation={0.3} mouseRepulsion repulsionStrength={1.1}
        clickWarp={false} intro={false} transparent opacity={0.75} dpr={1.25} />
    </div>
  )
}

// An accent word in a headline: sunlit cream with a light sheen passing over it now and then.
export function Accent({ children }) {
  return <ShinyText color={SUNLIT} shineColor="#ffffff" speed={3} delay={2.5} shineWidth={30} glow={0.25}>{children}</ShinyText>
}

// A headline number in a slow cream-to-earth-blue gradient.
export function BigNumber({ children }) {
  return <GradientText colors={[SUNLIT, '#ffffff', EARTH, SUNLIT]} animationSpeed={10} glow={0.35}>{children}</GradientText>
}

// A card whose border and surface light up around the pointer.
export function Spot({ as, className = '', children, ...rest }) {
  return (
    <SpotlightCard className={`spot ${className}`} spotlightColor="rgba(111, 182, 255, 0.9)" intensity={0.12} spotlightSize={320}
      borderGlow={0.7} proximity={90} grain={0.04} style={{ '--spotlight-card-surface': SURFACE }} {...rest}>
      {children}
    </SpotlightCard>
  )
}

// The primary call to action: an amber pill with a star travelling around its edge.
export function StarButton({ children, className = '', ...rest }) {
  return (
    <StarBorder className={`star-btn ${className}`} color="#ffffff" trailColor={EARTH} radius={4} duration={5} thickness={1.5}
      glow={0.6} backgroundColor="#ffffff" textColor="#05070c" borderColor="rgba(255, 255, 255, 0.25)" {...rest}>
      {children}
    </StarBorder>
  )
}

// A screenshot with a glossy streak on hover.
export function Glare({ children, className = '' }) {
  return (
    <GlareHover className={`glare ${className}`} width="100%" height="auto" borderRadius="16px" glareOpacity={0.22} glareSize={45}
      borderColor="rgba(255, 255, 255, 0.06)" background="transparent">
      {children}
    </GlareHover>
  )
}
