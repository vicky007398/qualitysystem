# Customer landing page

Public visitors see the product landing page at `/`. Signed-in users keep the existing dashboard at `/`. `/overview` always opens the public product overview, including when signed in. Demo buttons open `/login` for visitors and the dashboard for authenticated users.

The page explains guided IPQC entry, the four CTQ tests, review responsibilities, corrections, PDF downloads, and a practical pilot. Product screenshots were captured from a separate local database with simulated demonstration records. There are no invented customer testimonials, savings percentages, or certification claims in the landing-page copy.

Preview: [desktop](previews/landing-full.webp), [mobile](previews/landing-mobile.webp).

Verification: `python tools/landing_test.py`, account appearance checks, existing IPQC submission/approval/PDF validation, and browser checks at 360, 390, 768, 1024, and 1440 pixels. The landing page works without JavaScript; disclosure questions use native HTML.

This branch does not include the separate `green-pdf-theme` change. It has not been deployed to Render. The live demo previously lost records, so configure persistent storage and migrate or restore the existing demo data before publishing changes that restart that service.

## Supplied homepage photograph

The requested robot/solar-panel image arrived inline in chat without a downloadable file reference. Its exact original bytes are still needed. Upload the image directly to `static/product/` on this branch, named `home-background.png`, `home-background.jpg`, `home-background.jpeg`, or `home-background.webp` (keep the original format). The landing page detects the file and applies it automatically behind the main hero with a dark readability overlay. It uses a dark fallback without requesting missing image files until the asset is added. The existing product screenshots remain in the hero and feature sections.
