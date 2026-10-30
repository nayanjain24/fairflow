/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: '#06051a',
        panel: 'rgba(255, 255, 255, 0.04)',
        line: 'rgba(160, 140, 255, 0.16)',
        text: '#f1efff',
        mute: '#8f8ab3',
        accent: '#7c5cff',
        'accent-2': '#b79bff',
        pink: '#ff8fb8',
        safety: '#f26a1b',
        navy: '#0f2347',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      borderRadius: {
        glass: '26px',
      },
      boxShadow: {
        glass: '0 20px 60px -15px rgba(8, 6, 28, 0.7), inset 0 1px 0 0 rgba(183, 155, 255, 0.18)',
        'purple-glow': '0 0 32px rgba(124, 92, 255, 0.45)',
        'orange-glow': '0 0 36px rgba(242, 106, 27, 0.32)',
      },
    },
  },
  plugins: [],
}

