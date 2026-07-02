// Miroir EXACT de la config inline de index.html (avant : chargée via le CDN
// de dev cdn.tailwindcss.com). Sert à produire un CSS statique auto-hébergé.
const R = 'C:/Users/jorda/Triskell/triskell-command/triskell_command/web/ui';
module.exports = {
  darkMode: ['class', ':is([data-theme="dark"],[data-theme="mid"])'],
  content: [
    `${R}/index.html`,
    `${R}/login.html`,
    `${R}/scripts/**/*.js`,
  ],
  // Classes de couleur construites À LA VOLÉE par le code (health.js,
  // pipeline_view.js : `text-${tone}`) que le scan statique ne peut pas
  // deviner. Le CDN de dev les captait au runtime ; on les garantit ici.
  safelist: [
    'text-success', 'text-danger', 'text-warning', 'text-accent',
    'text-info', 'text-gold',
    'bg-success', 'bg-danger', 'bg-warning', 'bg-accent', 'bg-info',
    'border-success', 'border-danger', 'border-warning', 'border-accent',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui'],
        display: ['Cinzel', 'ui-serif', 'serif'],
      },
      colors: {
        bg:        'hsl(var(--bg) / <alpha-value>)',
        surface:   'hsl(var(--surface) / <alpha-value>)',
        'surface-elevated': 'hsl(var(--surface-elevated) / <alpha-value>)',
        border:    'hsl(var(--border) / <alpha-value>)',
        'border-strong': 'hsl(var(--border-strong) / <alpha-value>)',
        text:      'hsl(var(--text) / <alpha-value>)',
        'text-muted': 'hsl(var(--text-muted) / <alpha-value>)',
        'text-secondary': 'hsl(var(--text-secondary) / <alpha-value>)',
        accent:    'hsl(var(--accent) / <alpha-value>)',
        'accent-hover': 'hsl(var(--accent-hover) / <alpha-value>)',
        'accent-glow':  'hsl(var(--accent-glow) / <alpha-value>)',
        'accent-strong': 'hsl(var(--accent-strong) / <alpha-value>)',
        'accent-text':   'hsl(var(--accent-text) / <alpha-value>)',
        success:   'hsl(var(--success) / <alpha-value>)',
        'success-text': 'hsl(var(--success-text) / <alpha-value>)',
        warning:   'hsl(var(--warning) / <alpha-value>)',
        'warning-text': 'hsl(var(--warning-text) / <alpha-value>)',
        danger:    'hsl(var(--danger) / <alpha-value>)',
        'danger-text':  'hsl(var(--danger-text) / <alpha-value>)',
        info:      'hsl(var(--info) / <alpha-value>)',
        'info-text':    'hsl(var(--info-text) / <alpha-value>)',
        gold:      'hsl(var(--gold) / <alpha-value>)',
      },
      boxShadow: {
        'soft': '0 1px 2px rgba(15,23,42,0.04), 0 4px 12px rgba(15,23,42,0.06)',
        'lift': '0 4px 12px rgba(15,23,42,0.08), 0 12px 32px rgba(15,23,42,0.10)',
        'hero': '0 10px 40px rgba(99,102,241,0.18), 0 2px 8px rgba(15,23,42,0.06)',
        'fab':  '0 6px 16px rgba(99,102,241,0.32), 0 2px 6px rgba(15,23,42,0.10)',
      },
      animation: {
        'breathe': 'breathe 2.6s ease-in-out infinite',
        'pulse-fast': 'pulseFast 1.1s ease-in-out infinite',
        'fade-in':  'fadeIn 280ms ease-out forwards',
        'slide-up': 'slideUp 340ms cubic-bezier(0.16, 1, 0.3, 1) forwards',
      },
      keyframes: {
        breathe: {
          '0%,100%': { transform: 'scale(1)',  boxShadow: '0 6px 16px rgba(99,102,241,0.32)' },
          '50%':     { transform: 'scale(1.04)', boxShadow: '0 8px 24px rgba(99,102,241,0.45)' },
        },
        pulseFast: {
          '0%,100%': { transform: 'scale(1)',    boxShadow: '0 0 0 0 rgba(239,68,68,0.55)' },
          '50%':     { transform: 'scale(1.06)', boxShadow: '0 0 0 14px rgba(239,68,68,0)' },
        },
        fadeIn:  { 'from': { opacity: 0 }, 'to': { opacity: 1 } },
        slideUp: {
          'from': { opacity: 0, transform: 'translateY(12px)' },
          'to':   { opacity: 1, transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [require('@tailwindcss/forms'), require('@tailwindcss/typography')],
};
