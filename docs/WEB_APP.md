# Signalpost

Read-only Norwegian company intelligence. No database, authentication, payments, or server secrets. All company data comes from `public/data/profiles.json`.

## Data and static deployment

Replace `public/data/profiles.json` with the specified dataset schema, then run `pnpm install` and `pnpm build:static`. Deploy the resulting `out/` directory to any static host with directory-index support. Set its not-found page to `404.html`. Company pages are generated from the organisation numbers at build time, so rebuild after replacing the file, particularly when adding companies. Deploy at the domain root. `pnpm build` uses a standalone wrapper for JBOX preview compatibility; it does not introduce backend data or services.

The included sample contains EQUINOR ASA, TELENOR ASA and EQUINOR ENERGY AS. Facts are a limited extract of actual Brreg entity responses fetched during this build, with SHA-256 fingerprints of the exact response bytes and the full response retained in claim_span. Missing financial, social, hiring and leadership information is deliberately not invented. Registered employees are entity-level, not group workforce. Register website entries are not independent verification of website content. No ongoing monitoring is implied. Source licence: https://data.brreg.no/enhetsregisteret/api/dokumentasjon/no/ (NLOD).

Claims support primitive values, currency objects, nested objects and expandable arrays. For comparison, supported field/key aliases live in `lib/signalpost.ts` under `comparison`. Multiple matching claims select the lexically newest ISO reporting_period/as_of. Comparison never calculates missing figures or converts currencies. Unknown family keys appear after the eleven standard families. Citation numbers are deduplicated per company and link to original evidence. Missing evidence is labelled explicitly.

## GitHub export

Use JBOX's owner-controlled GitHub source publishing/export control and name the repository **Signalpost**. No repository has been created automatically by this source code. GitHub source export and publishing a live website are separate actions. Do not commit `.env*` files or secrets.

## Development

`pnpm dev`, `pnpm typecheck`, `pnpm build`. Internal component reference: `/design-system/`.

---

The original scaffold notes below are retained for framework reference only.

## Getting Started

First, run the development server:

```bash
pnpm dev
```

Open [http://localhost:3000/design-system](http://localhost:3000/design-system) with your browser to see the default empty route.

You can start editing the default empty page by modifying `app/design-system/page.tsx`. The page auto-updates as you edit the file.

Signalpost uses local system sans-serif, Georgia editorial headings and system monospace identifiers; there are no external font requests.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
