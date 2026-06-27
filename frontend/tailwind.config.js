/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Graph node colors
        memory: {
          DEFAULT: '#3B82F6', // blue-500
          light: '#93C5FD',   // blue-300
          dark: '#1D4ED8',    // blue-700
        },
        document: {
          DEFAULT: '#10B981', // emerald-500
          light: '#6EE7B7',   // emerald-300
          dark: '#047857',    // emerald-700
        },
        // Edge colors by type
        edge: {
          semantic: '#8B5CF6', // violet-500
          tag: '#F59E0B',      // amber-500
          docmem: '#6366F1',   // indigo-500
        },
      },
    },
  },
  plugins: [],
}
