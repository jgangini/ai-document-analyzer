/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'oracle-red': '#C74634',
        'oracle-dark-gray': '#312D2A',
        'oracle-medium-gray': '#4D4D4D',
        'oracle-light-gray': '#767676',
        'oracle-bg-gray': '#F6F6F6',
        'oracle-border': '#D9D9D9',
        'oracle-table-header': '#F5F2F0',
        'oracle-blue-link': '#0572CE',
        'oracle-green-accent': '#33553c',
      },
    },
  },
  plugins: [],
}
