# TODOS

## Frontend — Creches.pt

### [ ] Vercel CI/CD setup

**What:** Connect the GitHub repo to Vercel for automatic deployment on push to `main`.

**Why:** Without this, every deploy is manual. It's the backbone of the whole release process.

**How to apply:** Go to vercel.com → New Project → import `davidmarqu3s/childcare-directory` (or the Next.js app repo once it's separate). Set env vars: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_MAPBOX_TOKEN`. Enable preview deployments on PRs.

**Depends on:** Next.js app scaffolded.

---

### [ ] ISR revalidation trigger for data updates

**What:** When Carta Social data is updated in Supabase, trigger Vercel on-demand ISR revalidation for affected slugs.

**Why:** Detail pages are cached for 24h. Data updates quarterly. Without a trigger, cached pages serve stale info for up to 24h after an update. Fine for v1, but a proper setup uses Supabase database webhooks → Next.js `/api/revalidate` route.

**How to apply:**
1. Add `app/api/revalidate/route.ts` — accepts POST with `{ slug }`, calls `revalidatePath('/creche/[slug]')`, protected by a shared secret.
2. Set up Supabase webhook on `instituicoes` UPDATE → POST to the revalidation endpoint.

**Depends on:** Vercel CI/CD setup. Not needed for v1 launch.

---

### [ ] Mapbox loading UX on mobile ("Ver no mapa" button)

**What:** Add a loading spinner to the "Ver no mapa" button while Mapbox GL JS loads dynamically.

**Why:** Mapbox GL JS is ~270KB gzipped. On slow 4G in rural Portugal that's 2-4 seconds after the user taps. Without a loading state, the button appears frozen. Wire the spinner to the dynamic `import('mapbox-gl')` promise — show spinner on tap, hide when map is ready.

**How to apply:** In `MapPanel.tsx`, use `next/dynamic` with `{ loading: () => <Spinner /> }` or wire a manual loading state to the dynamic import.

**Depends on:** MapPanel.tsx implementation.
