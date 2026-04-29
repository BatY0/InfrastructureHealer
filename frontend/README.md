# KubeQuest Frontend

React + TypeScript frontend for the KubeQuest AI infrastructure simulator.

## Responsibilities

- Render scenario selection and progression UI
- Show live pod state from backend polling
- Provide mentor chat interface
- Provide sandbox terminal interface
- Display post-scenario feedback and progression stats

## Local Development

From `frontend/`:

```bash
npm install
npm run dev
```

Default dev URL: `http://localhost:5173`

The frontend expects backend API at `http://127.0.0.1:8000` (configured in `src/App.tsx`).

## Scripts

- `npm run dev` - start Vite dev server
- `npm run build` - production build
- `npm run preview` - preview built bundle
- `npm run lint` - run ESLint

## Main UI Areas

- **Left panel:** level selection and live pod dashboard
- **Top-right panel:** mentor chat
- **Bottom-right panel:** command terminal
- **Modals:** level briefing and post-mortem summary

## Notes

- Scenario text, briefings, and victory logic come from backend (`chaos_injector.py`).
- Mentor behavior is controlled by backend prompt rules (`engine.py`).
